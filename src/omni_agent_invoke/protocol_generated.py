# Generated identity contract v1. SHA-256: e37f9facc6af9737602a06c31801c76efbd39ffa4fe6f96ac220d0c841c35176. MIT License.
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
