import configparser
import itertools
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

if False:
    import boto3  # type: ignore
import wandb
import wandb.docker as docker
from wandb.errors import CommError, LaunchError
from wandb.util import get_module

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import (
    get_entry_point_command,
    LaunchProject,
)
from ..docker import (
    build_docker_image_if_needed,
    construct_local_image_uri,
    docker_image_exists,
    docker_image_inspect,
    generate_docker_base_image,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import PROJECT_DOCKER_ARGS


_logger = logging.getLogger(__name__)


class SagemakerSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command on aws sagemaker."""

    def __init__(self, training_job_name: str, client: "boto3.Client") -> None:
        super().__init__()
        self.client = client
        self.training_job_name = training_job_name
        self._status = Status("running")

    @property
    def id(self) -> str:
        return f"sagemaker-{self.training_job_name}"

    def wait(self) -> bool:
        while True:
            status_state = self.get_status().state
            if status_state in ["stopped", "failed", "finished"]:
                break
            time.sleep(5)
        return status_state == "finished"

    def cancel(self) -> None:
        # Interrupt child process if it hasn't already exited
        status = self.get_status()
        if status.state == "running":
            self.client.stop_training_job(TrainingJobName=self.training_job_name)
            self.wait()

    def get_status(self) -> Status:
        job_status = self.client.describe_training_job(
            TrainingJobName=self.training_job_name
        )["TrainingJobStatus"]
        if job_status == "Completed":
            self._status = Status("finished")
        elif job_status == "Failed":
            self._status = Status("failed")
        elif job_status == "Stopping":
            self._status = Status("stopping")
        elif job_status == "Stopped":
            self._status = Status("finished")
        elif job_status == "InProgress":
            self._status = Status("running")
        return self._status


class AWSSagemakerRunner(AbstractRunner):
    """Runner class, uses a project to create a SagemakerSubmittedRun."""

    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        _logger.info("using AWSSagemakerRunner")
        boto3 = get_module("boto3", "AWSSagemakerRunner requires boto3 to be installed")
        validate_docker_installation()
        if launch_project.resource_args.get("ecr_repo_name") is None:
            raise LaunchError(
                "AWS Sagemaker jobs require an ecr repository name, set this using `--resource_args ecr_repo_name=<ecr_repo_name>`"
            )
        if get_role_arn(launch_project.resource_args) is None:
            raise LaunchError(
                "AWS sagemaker jobs, set this using `resource_args RoleArn=<role_arn>` or `resource_args role_arn=<role_arn>`"
            )
        if launch_project.resource_args.get("OutputDataConfig") is None:
            raise LaunchError(
                "AWS sagemaker jobs, set this using `resource_args OutputDataConfig=<output_data_config>`"
            )
        region = get_region(launch_project)

        access_key, secret_key = get_aws_credentials()

        # if the user provided the image they want to use, use that, but warn it won't have swappable artifacts
        if (
            launch_project.resource_args.get("AlgorithmSpecification", {}).get(
                "TrainingImage"
            )
            is not None
        ):
            wandb.termwarn(
                "Using user provided ECR image, this image will not be able to swap artifacts"
            )
            sagemaker_client = boto3.client(
                "sagemaker",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            sagemaker_args = build_sagemaker_args(launch_project)
            _logger.info(
                f"Launching sagemaker job on user supplied image with args: {sagemaker_args}"
            )
            run = launch_sagemaker_job(launch_project, sagemaker_args, sagemaker_client)
            return run
        _logger.info("Connecting to AWS ECR Client")
        ecr_client = boto3.client(
            "ecr",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        token = ecr_client.get_authorization_token()

        ecr_repo_name = launch_project.resource_args.get("ecr_repo_name")
        aws_registry = (
            token["authorizationData"][0]["proxyEndpoint"].replace("https://", "")
            + f"/{ecr_repo_name}"
        )

        if self.backend_config[PROJECT_DOCKER_ARGS]:
            wandb.termwarn(
                "Docker args are not supported for AWS. Not using docker args"
            )

        entry_point = launch_project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = True
        if launch_project.docker_image:
            pull_docker_image(launch_project.docker_image)
            copy_code = False
        else:
            # TODO: potentially pull the base_image
            if not docker_image_exists(launch_project.base_image):
                if generate_docker_base_image(launch_project, entry_cmd) is None:
                    raise LaunchError("Unable to build base image")
            else:
                wandb.termlog(
                    "Using existing base image: {}".format(launch_project.base_image)
                )

        command_args = []

        container_inspect = docker_image_inspect(launch_project.base_image)
        container_workdir = container_inspect["ContainerConfig"].get("WorkingDir", "/")
        container_env: List[str] = container_inspect["ContainerConfig"]["Env"]

        if launch_project.docker_image is None or launch_project.build_image:
            image_uri = construct_local_image_uri(launch_project)
            command_args += get_entry_point_command(
                entry_point, launch_project.override_args
            )
            # create a flattened list of all the command inputs for the dockerfile
            command_args = list(
                itertools.chain(*[ca.split(" ") for ca in command_args])
            )
            _logger.info("Building docker image")
            image = build_docker_image_if_needed(
                launch_project=launch_project,
                api=self._api,
                copy_code=copy_code,
                workdir=container_workdir,
                container_env=container_env,
                runner_type="aws",
                image_uri=image_uri,
                command_args=command_args,
            )
        else:
            # TODO: rewrite env vars and copy code in supplied docker image
            wandb.termwarn(
                "Using supplied docker image: {}. Artifact swapping and launch metadata disabled".format(
                    launch_project.docker_image
                )
            )
            image_uri = launch_project.docker_image
        _logger.info("Logging in to AWS ECR")
        login_resp = aws_ecr_login(region, aws_registry)
        if "Login Succeeded" not in login_resp:
            raise LaunchError(f"Unable to login to ECR, response: {login_resp}")

        aws_tag = f"{aws_registry}:{launch_project.run_id}"
        docker.tag(image, aws_tag)
        _logger.info(f"Pushing image {image} to registy {aws_registry}")
        push_resp = docker.push(aws_registry, launch_project.run_id)
        if push_resp is None:
            raise LaunchError("Failed to push image to repository")
        if f"The push refers to repository [{aws_registry}]" not in push_resp:
            raise LaunchError(f"Unable to push image to ECR, response: {push_resp}")

        if self.backend_config.get("runQueueItemId"):
            try:
                self._api.ack_run_queue_item(
                    self.backend_config["runQueueItemId"], launch_project.run_id
                )
            except CommError:
                wandb.termerror(
                    "Error acking run queue item. Item lease may have ended or another process may have acked it."
                )
                return None
        _logger.info("Connecting to sagemaker client")
        sagemaker_client = boto3.client(
            "sagemaker",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        wandb.termlog(
            "Launching run on sagemaker with entrypoint: {}".format(
                " ".join(command_args)
            )
        )

        sagemaker_args = build_sagemaker_args(launch_project, aws_tag)
        _logger.info(f"Launching sagemaker job with args: {sagemaker_args}")
        run = launch_sagemaker_job(launch_project, sagemaker_args, sagemaker_client)
        return run


def aws_ecr_login(region: str, registry: str) -> str:
    pw_command = f"aws ecr get-login-password --region {region}".split(" ")
    try:
        pw_process = subprocess.run(
            pw_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
    except subprocess.CalledProcessError:
        raise LaunchError(
            "Unable to get login password. Please ensure you have AWS credentials configured"
        )

    try:
        login_process = subprocess.run(
            f"docker login --username AWS --password-stdin {registry}".split(" "),
            input=pw_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise LaunchError("Failed to login to ECR")
    return login_process.stdout.decode("utf-8")


def merge_aws_tag_with_algorithm_specification(
    algorithm_specification: Optional[Dict[str, Any]], aws_tag: Optional[str]
) -> Dict[str, Any]:
    """
    AWS Sagemaker algorithms require a training image and an input mode.
    If the user does not specify the specification themselves, define the spec
    minimally using these two fields. Otherwise, if they specify the AlgorithmSpecification
    set the training image if it is not set.
    """
    if algorithm_specification is None:
        return {
            "TrainingImage": aws_tag,
            "TrainingInputMode": "File",
        }
    elif algorithm_specification.get("TrainingImage") is None:
        algorithm_specification["TrainingImage"] = aws_tag
    if algorithm_specification["TrainingImage"] is None:
        raise LaunchError("Failed determine tag for training image")
    return algorithm_specification


def build_sagemaker_args(
    launch_project: LaunchProject, aws_tag: Optional[str] = None
) -> Dict[str, Any]:
    sagemaker_args = {}
    resource_args = launch_project.resource_args
    sagemaker_args["TrainingJobName"] = (
        resource_args.get("TrainingJobName") or launch_project.run_id
    )
    sagemaker_args[
        "AlgorithmSpecification"
    ] = merge_aws_tag_with_algorithm_specification(
        resource_args.get("AlgorithmSpecification"), aws_tag,
    )
    sagemaker_args["ResourceConfig"] = resource_args.get("ResourceConfig") or {
        "InstanceCount": 1,
        "InstanceType": "ml.m4.xlarge",
        "VolumeSizeInGB": 2,
    }

    sagemaker_args["StoppingCondition"] = resource_args.get("StoppingCondition") or {
        "MaxRuntimeInSeconds": resource_args.get("MaxRuntimeInSeconds") or 3600
    }
    output_data_config = resource_args.get("OutputDataConfig")

    sagemaker_args["OutputDataConfig"] = output_data_config
    sagemaker_args["RoleArn"] = get_role_arn(resource_args)
    return sagemaker_args


def launch_sagemaker_job(
    launch_project: LaunchProject,
    sagemaker_args: Dict[str, Any],
    sagemaker_client: "boto3.Client",
) -> SagemakerSubmittedRun:
    training_job_name = (
        launch_project.resource_args.get("TrainingJobName") or launch_project.run_id
    )
    resp = sagemaker_client.create_training_job(**sagemaker_args)

    if resp.get("TrainingJobArn") is None:
        raise LaunchError("Unable to create training job")

    run = SagemakerSubmittedRun(training_job_name, sagemaker_client)
    wandb.termlog("Run job submitted with arn: {}".format(resp.get("TrainingJobArn")))
    return run


def get_region(launch_project: LaunchProject) -> str:
    region = launch_project.resource_args.get("region")
    if region is None and os.path.exists(os.path.expanduser("~/.aws/config")):
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.aws/config"))
        section = launch_project.resource_args.get("config_section") or "default"
        try:
            region = config.get(section, "region")
        except (configparser.NoOptionError, configparser.NoSectionError):
            raise LaunchError(
                "Unable to detemine default region from ~/.aws/config. "
                "Please specify region in resource args or specify config "
                "section as 'aws_config_section'"
            )

    if region is None:
        raise LaunchError(
            "AWS region not specified and ~/.aws/config not found. Configure AWS"
        )
    assert isinstance(region, str)
    return region


def get_aws_credentials() -> Tuple[str, str]:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if (
        access_key is None
        or secret_key is None
        and os.path.exists(os.path.expanduser("~/.aws/credentials"))
    ):
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.aws/credentials"))
        access_key = config.get("default", "aws_access_key_id")
        secret_key = config.get("default", "aws_secret_access_key")
    if access_key is None or secret_key is None:
        raise LaunchError("AWS credentials not found")
    return access_key, secret_key


def get_role_arn(resource_args: Dict[str, Any]) -> Optional[str]:
    role_arn = resource_args.get("RoleArn") or resource_args.get("role_arn")
    return role_arn
