"""
settings test.
"""

import copy
import datetime
import os
from unittest import mock

import pytest  # type: ignore
import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_settings


Property = wandb_settings.Property
Settings = wandb_settings.Settings
Source = wandb_settings.Source


# test Property class
def test_property_init():
    p = Property(name="foo", value=1)
    assert p.name == "foo"
    assert p.value == 1
    assert p._source == Source.BASE
    assert not p._is_policy


def test_property_preprocess_and_validate():
    p = Property(
        name="foo",
        value=1,
        preprocessor=lambda x: str(x),
        validator=lambda x: isinstance(x, str),
    )
    assert p.name == "foo"
    assert p.value == "1"
    assert p._source == Source.BASE
    assert not p._is_policy


def test_property_preprocess_validate_hook():
    p = Property(
        name="foo",
        value="2",
        preprocessor=lambda x: int(x),
        validator=lambda x: isinstance(x, int),
        hook=lambda x: x ** 2,
        source=Source.OVERRIDE,
    )
    assert p._source == Source.OVERRIDE
    assert p.value == 4
    assert not p._is_policy


def test_property_multiple_validators():
    def meaning_of_life(x):
        return x == 42

    p = Property(
        name="foo", value=42, validator=[lambda x: isinstance(x, int), meaning_of_life],
    )
    assert p.value == 42
    with pytest.raises(ValueError):
        p.update(value=43)


def test_property_update():
    p = Property(name="foo", value=1)
    p.update(value=2)
    assert p.value == 2


def test_property_update_sources():
    p = Property(name="foo", value=1, source=Source.ORG)
    assert p.value == 1
    # smaller source => lower priority
    # lower priority:
    p.update(value=2, source=Source.BASE)
    assert p.value == 1
    # higher priority:
    p.update(value=3, source=Source.USER)
    assert p.value == 3


def test_property_update_policy_sources():
    p = Property(name="foo", value=1, is_policy=True, source=Source.ORG)
    assert p.value == 1
    # smaller source => higher priority
    # higher priority:
    p.update(value=2, source=Source.BASE)
    assert p.value == 2
    # higher priority:
    p.update(value=3, source=Source.USER)
    assert p.value == 2


def test_property_set_value_directly_forbidden():
    p = Property(name="foo", value=1)
    with pytest.raises(AttributeError):
        p.value = 2


def test_property_update_frozen_forbidden():
    p = Property(name="foo", value=1, frozen=True)
    with pytest.raises(TypeError):
        p.update(value=2)


# test Settings class


def test_attrib_get():
    s = Settings()
    assert s.base_url == "https://api.wandb.ai"


def test_attrib_set_not_allowed():
    s = Settings()
    with pytest.raises(TypeError):
        s.base_url = "new"


def test_attrib_get_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing


def test_update_override():
    s = Settings()
    s.update(dict(base_url="something2"), source=Source.OVERRIDE)
    assert s.base_url == "something2"


def test_update_priorities():
    s = Settings()
    # USER has higher priority than ORG (and both are higher priority than BASE)
    s.update(dict(base_url="foo"), source=Source.USER)
    assert s.base_url == "foo"
    s.update(dict(base_url="bar"), source=Source.ORG)
    assert s.base_url == "foo"


def test_update_priorities_order():
    s = Settings()
    # USER has higher priority than ORG (and both are higher priority than BASE)
    s.update(dict(base_url="bar"), source=Source.ORG)
    assert s.base_url == "bar"
    s.update(dict(base_url="foo"), source=Source.USER)
    assert s.base_url == "foo"


def test_update_missing_attrib():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(missing="nope"), source=Source.OVERRIDE)


def test_update_kwargs():
    s = Settings()
    s.update(base_url="something")
    assert s.base_url == "something"


def test_update_both():
    s = Settings()
    s.update(dict(base_url="something"), project="nothing")
    assert s.base_url == "something"
    assert s.project == "nothing"


def test_ignore_globs():
    s = Settings()
    assert s.ignore_globs == ()


def test_ignore_globs_explicit():
    s = Settings(ignore_globs=["foo"])
    assert s.ignore_globs == ("foo",)


def test_ignore_globs_env():
    s = Settings()
    s.apply_env_vars({"WANDB_IGNORE_GLOBS": "foo"})
    assert s.ignore_globs == ("foo",)

    s = Settings()
    s.apply_env_vars({"WANDB_IGNORE_GLOBS": "foo,bar"})
    assert s.ignore_globs == ("foo", "bar",)


def test_quiet():
    s = Settings()
    assert s._quiet is None
    s = Settings(quiet=True)
    assert s._quiet
    s = Settings()
    s.apply_env_vars({"WANDB_QUIET": "false"})
    assert not s._quiet


@pytest.mark.skip(reason="I need to make my mock work properly with new settings")
def test_ignore_globs_settings(local_settings):
    with open(os.path.join(os.getcwd(), ".config", "wandb", "settings"), "w") as f:
        f.write(
            """[default]
ignore_globs=foo,bar"""
        )
    s = Settings(_files=True)
    assert s.ignore_globs == ("foo", "bar",)


def test_copy():
    s = Settings()
    s.update(base_url="changed")
    s2 = copy.copy(s)
    assert s2.base_url == "changed"
    s.update(base_url="notchanged")
    assert s.base_url == "notchanged"
    assert s2.base_url == "changed"


def test_update_linked_properties():
    s = Settings()
    # sync_dir depends, among other things, on run_mode
    assert s.mode == "online"
    assert s.run_mode == "run"
    assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)
    s.update(mode="offline")
    assert s.mode == "offline"
    assert s.run_mode == "offline-run"
    assert "offline-run" in s.sync_dir


def test_copy_update_linked_properties():
    s = Settings()
    assert s.mode == "online"
    assert s.run_mode == "run"
    assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)

    s2 = copy.copy(s)
    assert s2.mode == "online"
    assert s2.run_mode == "run"
    assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

    s.update(mode="offline")
    assert s.mode == "offline"
    assert s.run_mode == "offline-run"
    assert "offline-run" in s.sync_dir
    assert s2.mode == "online"
    assert s2.run_mode == "run"
    assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

    s2.update(mode="offline")
    assert s2.mode == "offline"
    assert s2.run_mode == "offline-run"
    assert "offline-run" in s2.sync_dir


def test_invalid_dict():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(invalid="new"))


def test_invalid_kwargs():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(invalid="new")


def test_invalid_both():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(project="ok"), invalid="new")
    assert s.project != "ok"
    with pytest.raises(KeyError):
        s.update(dict(wrong="bad", entity="nope"), project="okbutnotset")
    assert s.entity != "nope"
    assert s.project != "okbutnotset"


def test_freeze():
    s = Settings()
    s.update(project="goodprojo")
    assert s.project == "goodprojo"
    s.freeze()
    assert s.is_frozen()
    with pytest.raises(TypeError):
        s.update(project="badprojo")
    assert s.project == "goodprojo"
    with pytest.raises(TypeError):
        s.update(project="badprojo2")
    c = copy.copy(s)
    assert c.project == "goodprojo"
    c.update(project="changed")
    assert c.project == "changed"
    assert s.project == "goodprojo"


def test_bad_choice():
    s = Settings()
    with pytest.raises(TypeError):
        s.mode = "goodprojo"
    with pytest.raises(UsageError):
        s.update(mode="badmode")


def test_priority_update_greater_source():
    s = Settings()
    # for a non-policy setting, greater source (PROJECT) has higher priority
    s.update(project="pizza", source=Source.ENTITY)
    assert s.project == "pizza"
    s.update(project="pizza2", source=Source.PROJECT)
    assert s.project == "pizza2"


def test_priority_update_smaller_source():
    s = Settings()
    s.update(project="pizza", source=Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", source=Source.ENTITY)
    # for a non-policy setting, greater source (PROJECT) has higher priority
    assert s.project == "pizza"


def test_priority_update_policy_greater_source():
    s = Settings()
    # for a policy setting, greater source (PROJECT) has lower priority
    s.update(summary_warnings=42, source=Source.PROJECT)
    assert s.summary_warnings == 42
    s.update(summary_warnings=43, source=Source.ENTITY)
    assert s.summary_warnings == 43


def test_priority_update_policy_smaller_source():
    s = Settings()
    # for a policy setting, greater source (PROJECT) has lower priority
    s.update(summary_warnings=42, source=Source.ENTITY)
    assert s.summary_warnings == 42
    s.update(summary_warnings=43, source=Source.PROJECT)
    assert s.summary_warnings == 42


def test_validate_base_url():
    s = Settings()
    with pytest.raises(UsageError):
        s.update(base_url="https://wandb.ai")
    with pytest.raises(UsageError):
        s.update(base_url="https://app.wandb.ai")
    with pytest.raises(UsageError):
        s.update(base_url="http://api.wandb.ai")
    s.update(base_url="https://api.wandb.ai")
    assert s.base_url == "https://api.wandb.ai"
    s.update(base_url="https://wandb.ai.other.crazy.domain.com")
    assert s.base_url == "https://wandb.ai.other.crazy.domain.com"


def test_preprocess_base_url():
    s = Settings()
    s.update(base_url="http://host.com")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com/")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com///")
    assert s.base_url == "http://host.com"
    s.update(base_url="//http://host.com//")
    assert s.base_url == "//http://host.com"


def test_code_saving_save_code_env_false(live_mock_server, test_settings):
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE="false"):
        # first, ditch user preference for code saving
        # since it has higher priority for policy settings
        live_mock_server.set_ctx({"code_saving_enabled": None})
        # note that save_code is a policy by definition
        test_settings.update({"save_code": None}, source=Source.SETTINGS)
        run = wandb.init(settings=test_settings)
        assert run._settings.save_code is False
        run.finish()


def test_code_saving_disable_code(live_mock_server, test_settings):
    with mock.patch.dict("os.environ", WANDB_DISABLE_CODE="true"):
        # first, ditch user preference for code saving
        # since it has higher priority for policies
        live_mock_server.set_ctx({"code_saving_enabled": None})
        # note that save_code is a policy by definition
        test_settings.update({"save_code": None}, source=Source.SETTINGS)
        run = wandb.init(settings=test_settings)
        assert run._settings.save_code is False
        run.finish()


def test_redact():
    # normal redact case
    redacted = wandb_settings._redact_dict({"this": 2, "that": 9, "api_key": "secret"})
    assert redacted == {"this": 2, "that": 9, "api_key": "***REDACTED***"}

    # two redacted keys with options passed
    redacted = wandb_settings._redact_dict(
        {"ok": "keep", "unsafe": 9, "bad": "secret"},
        unsafe_keys={"unsafe", "bad"},
        redact_str="OMIT",
    )
    assert redacted == {"ok": "keep", "unsafe": "OMIT", "bad": "OMIT"}

    # all keys fine
    redacted = wandb_settings._redact_dict({"all": "keep", "good": 9, "keys": "fine"})
    assert redacted == {"all": "keep", "good": 9, "keys": "fine"}

    # empty case
    redacted = wandb_settings._redact_dict({})
    assert redacted == {}

    # all keys redacted
    redacted = wandb_settings._redact_dict({"api_key": "secret"})
    assert redacted == {"api_key": "***REDACTED***"}


def test_offline(test_settings):
    assert test_settings._offline is False
    test_settings.update({"disabled": True}, source=Source.BASE)
    assert test_settings._offline is True
    test_settings.update({"disabled": None}, source=Source.BASE)
    test_settings.update({"mode": "dryrun"}, source=Source.BASE)
    assert test_settings._offline is True
    test_settings.update({"mode": "offline"}, source=Source.BASE)
    assert test_settings._offline is True


def test_silent(test_settings):
    test_settings.update({"silent": "true"}, source=Source.BASE)
    assert test_settings._silent is True


def test_silent_run(live_mock_server, test_settings):
    test_settings.update({"silent": "true"}, source=Source.SETTINGS)
    assert test_settings._silent is True
    run = wandb.init(settings=test_settings)
    assert run._settings._silent is True
    run.finish()


def test_silent_env_run(live_mock_server, test_settings):
    with mock.patch.dict("os.environ", WANDB_SILENT="true"):
        run = wandb.init(settings=test_settings)
        assert run._settings._silent is True
        run.finish()


def test_strict():
    settings = Settings(strict=True)
    assert settings.strict is True
    assert settings._strict is True

    settings = Settings(strict=False)
    assert not settings.strict
    assert settings._strict is None


def test_strict_run(live_mock_server, test_settings):
    test_settings.update({"strict": "true"}, source=Source.SETTINGS)
    assert test_settings._strict is True
    run = wandb.init(settings=test_settings)
    assert run._settings._strict is True
    run.finish()


def test_show_info(test_settings):
    test_settings.update({"show_info": True}, source=Source.BASE)
    assert test_settings._show_info is True

    test_settings.update({"show_info": False}, source=Source.BASE)
    assert test_settings._show_info is None


def test_show_info_run(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._show_info is True
    run.finish()


def test_show_info_false_run(live_mock_server, test_settings):
    test_settings.update({"show_info": "false"}, source=Source.SETTINGS)
    run = wandb.init(settings=test_settings)
    assert run._settings._show_info is None
    run.finish()


def test_show_warnings(test_settings):
    test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
    assert test_settings._show_warnings is True

    test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
    assert test_settings._show_warnings is None


def test_show_warnings_run(live_mock_server, test_settings):
    test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
    run = wandb.init(settings=test_settings)
    assert run._settings._show_warnings is True
    run.finish()


def test_show_warnings_false_run(live_mock_server, test_settings):
    test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
    run = wandb.init(settings=test_settings)
    assert run._settings._show_warnings is None
    run.finish()


def test_show_errors(test_settings):
    test_settings.update({"show_errors": True}, source=Source.SETTINGS)
    assert test_settings._show_errors is True

    test_settings.update({"show_errors": False}, source=Source.SETTINGS)
    assert test_settings._show_errors is None


def test_show_errors_run(test_settings):
    test_settings.update({"show_errors": True}, source=Source.SETTINGS)
    run = wandb.init(settings=test_settings)
    assert run._settings._show_errors is True
    run.finish()


def test_show_errors_false_run(test_settings):
    test_settings.update({"show_errors": False}, source=Source.SETTINGS)
    run = wandb.init(settings=test_settings)
    assert run._settings._show_errors is None
    run.finish()


def test_noop(test_settings):
    test_settings.update({"mode": "disabled"}, source=Source.BASE)
    assert test_settings._noop is True


def test_not_jupyter(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._jupyter is False
    run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_console(runner, test_settings):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.console == "auto"
        assert run._settings._console == wandb_settings.SettingsConsole.REDIRECT
        test_settings.update({"console": "off"}, source=Source.BASE)
        assert test_settings._console == wandb_settings.SettingsConsole.OFF
        test_settings.update({"console": "wrap"}, source=Source.BASE)
        assert test_settings._console == wandb_settings.SettingsConsole.WRAP
        run.finish()


@mock.patch.dict(
    os.environ, {"WANDB_START_METHOD": "thread", "USERNAME": "test"}, clear=True
)
def test_console_run(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.console == "auto"
        assert run._settings._console == wandb_settings.SettingsConsole.WRAP
        run.finish()


def test_validate_console_problem_anonymous():
    s = Settings()
    with pytest.raises(UsageError):
        s.update(console="lol")
    with pytest.raises(UsageError):
        s.update(problem="lol")
    with pytest.raises(UsageError):
        s.update(anonymous="lol")


def test_resume_fname(test_settings):
    assert test_settings.resume_fname == os.path.abspath(
        os.path.join("./wandb", "wandb-resume.json")
    )


def test_resume_fname_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.resume_fname == os.path.join(
        run._settings.root_dir, "wandb", "wandb-resume.json"
    )
    run.finish()


def test_wandb_dir(test_settings):
    assert os.path.abspath(test_settings.wandb_dir) == os.path.abspath("wandb/")


def test_wandb_dir_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
        os.path.join(run._settings.root_dir, "wandb/")
    )
    run.finish()


def test_log_user(test_settings):
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_user)
    ).rsplit("/", 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug.log"


def test_log_internal(test_settings):
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_internal)
    ).rsplit("/", 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug-internal.log"


# note: patching os.environ because other tests may have created env variables
# that are not in the default environment, which would cause these test to fail.
# setting {"USERNAME": "test"} because on Windows getpass.getuser() would otherwise fail.
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_dir(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.sync_dir == os.path.realpath("./wandb/latest-run")
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_file(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.sync_file == os.path.realpath(
            f"./wandb/latest-run/run-{run.id}.wandb"
        )
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_files_dir(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.files_dir == os.path.realpath("./wandb/latest-run/files")
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_tmp_dir(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings.tmp_dir == os.path.realpath("./wandb/latest-run/tmp")
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_tmp_code_dir(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert run._settings._tmp_code_dir == os.path.realpath(
            "./wandb/latest-run/tmp/code"
        )
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_log_symlink_user(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert os.path.realpath(run._settings.log_symlink_user) == os.path.abspath(
            run._settings.log_user
        )
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_log_symlink_internal(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert os.path.realpath(run._settings.log_symlink_internal) == os.path.abspath(
            run._settings.log_internal
        )
        run.finish()


@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_symlink_latest(runner):
    with runner.isolated_filesystem():
        run = wandb.init(mode="offline")
        assert os.path.realpath(run._settings.sync_symlink_latest) == os.path.abspath(
            "./wandb/offline-run-{}-{}".format(
                datetime.datetime.strftime(
                    run._settings._start_datetime, "%Y%m%d_%H%M%S"
                ),
                run.id,
            )
        )
        run.finish()


def test_settings_system(test_settings):
    assert os.path.abspath(test_settings.settings_system) == os.path.expanduser(
        "~/.config/wandb/settings"
    )


def test_override_login_settings(live_mock_server, test_settings):
    wlogin = wandb_login._WandbLogin()
    login_settings = test_settings.copy()
    login_settings.update(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_override_login_settings_with_dict(live_mock_server, test_settings):
    wlogin = wandb_login._WandbLogin()
    login_settings = dict(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_start_run():
    s = Settings()
    s._start_run()
    assert s._Settings_start_time is not None
    assert s._Settings_start_datetime is not None


def test_unexpected_arguments():
    with pytest.raises(TypeError):
        Settings(lol=False)


def test_mapping_interface():
    s = Settings()
    for setting in s:
        assert setting in s


def test_make_static_include_not_properties():
    s = Settings()
    static_settings = s.make_static(include_properties=False)
    assert "run_mode" not in static_settings
    static_settings = s.make_static(include_properties=True)
    assert "run_mode" in static_settings


def test_is_local():
    s = Settings(base_url=None)
    assert s.is_local is False
