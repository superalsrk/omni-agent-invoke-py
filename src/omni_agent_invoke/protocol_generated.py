# Generated identity contract v2. SHA-256: dd65e267834a6aca67410a4b268f915b485c9355c3a027225391f06c31012adc. MIT License.
from typing import Literal, TypedDict

ProtocolMode = Literal["canonical", "native"]


class LookupKey(TypedDict):
    run_id: str
    invocation_id: str
    agent_session_id: str
    session_generation: int
    protocol_mode: ProtocolMode


class RunRef(TypedDict):
    run_id: str
    invocation_id: str
    agent_session_id: str
    session_generation: int
    protocol_mode: ProtocolMode
    kernel_instance_id: str
    stream_id: str
    protocol: str


METHODS = {
    "status": "status",
    "list": "adapter.list",
    "invoke": "agent_run.invoke",
    "get": "agent_run.get",
    "subscribe": "agent_run.subscribe",
    "cancel": "agent_run.cancel",
    "respond": "agent_run.respond",
    "respondNative": "agent_run.native.respond",
}
