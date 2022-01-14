"""
@generated by mypy-protobuf.  Do not edit manually!
isort:skip_file
"""
import builtins
import google.protobuf.descriptor
import google.protobuf.message
import typing
import typing_extensions

DESCRIPTOR: google.protobuf.descriptor.FileDescriptor = ...

class _RecordInfo(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor = ...
    STREAM_ID_FIELD_NUMBER: builtins.int
    _DEBUG_LOG_ID_FIELD_NUMBER: builtins.int
    stream_id: typing.Text = ...
    _debug_log_id: typing.Text = ...

    def __init__(self,
        *,
        stream_id : typing.Text = ...,
        _debug_log_id : typing.Text = ...,
        ) -> None: ...
    def ClearField(self, field_name: typing_extensions.Literal[u"_debug_log_id",b"_debug_log_id",u"stream_id",b"stream_id"]) -> None: ...
global____RecordInfo = _RecordInfo

class _RequestInfo(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor = ...
    STREAM_ID_FIELD_NUMBER: builtins.int
    stream_id: typing.Text = ...

    def __init__(self,
        *,
        stream_id : typing.Text = ...,
        ) -> None: ...
    def ClearField(self, field_name: typing_extensions.Literal[u"stream_id",b"stream_id"]) -> None: ...
global____RequestInfo = _RequestInfo

class _ResultInfo(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor = ...
    _DEBUG_LOG_ID_FIELD_NUMBER: builtins.int
    _debug_log_id: typing.Text = ...

    def __init__(self,
        *,
        _debug_log_id : typing.Text = ...,
        ) -> None: ...
    def ClearField(self, field_name: typing_extensions.Literal[u"_debug_log_id",b"_debug_log_id"]) -> None: ...
global____ResultInfo = _ResultInfo
