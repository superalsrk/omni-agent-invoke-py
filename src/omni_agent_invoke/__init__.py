"""Native Python API for unified agent execution through Octo Runtime."""

from copy import deepcopy
from uuid import uuid4
import base64
import hashlib
from typing import Literal, TypedDict
from .kernel import KernelClient, KernelError, validate
from .protocol_generated import ProtocolMode as ProtocolModeLiteral


class AgentEnvItem(TypedDict):
    namespace: str
    name: str
    payload: dict


class AgentEnv(TypedDict):
    schema: Literal["octo.context-envelope/v3"]
    items: list[AgentEnvItem]


__all__ = ["Client", "KernelError", "AgentEnv", "AgentEnvItem", "build_input", "image_input"]


def image_input(data: bytes, mime_type: str) -> dict:
    if (
        mime_type not in ("image/png", "image/jpeg", "image/webp")
        or not 0 < len(data) <= 2_097_152
    ):
        raise ValueError("Expected PNG, JPEG or WebP bytes up to 2 MiB")
    return {
        "type": "image",
        "mimeType": mime_type,
        "data": base64.b64encode(data).decode("ascii"),
        "byteSize": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build_input(
    inputs: list[dict],
    agent_env: AgentEnv,
    mode: ProtocolModeLiteral = "native",
) -> dict:
    """Snapshot complete caller-owned inputs and agentEnv without adding content."""
    request = {
        "runId": str(uuid4()),
        "invocationId": str(uuid4()),
        "sessionId": str(uuid4()),
        "sessionGeneration": 0,
        "protocol_mode": mode,
        "inputs": deepcopy(inputs),
        "agentEnv": deepcopy(agent_env),
    }
    validate("InvokeInputWire", request)
    return request


def _text_input(adapter, prompt, mode):
    return build_input(
        [{"type": "text", "text": prompt}],
        {
            "schema": "octo.context-envelope/v3",
            "items": [
                {"namespace": "octo.execution", "name": "adapter", "payload": {"type": adapter}}
            ],
        },
        mode,
    )


class Client:
    def __init__(self, endpoint):
        self.kernel = KernelClient(endpoint)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self.kernel.close()

    async def status(self):
        return await self.kernel.status()

    async def list(self):
        return await self.kernel.list()

    def invoke(self, adapter: str, prompt: str):
        return self.invoke_input(_text_input(adapter, prompt, "canonical"))

    def invoke_native(self, adapter: str, prompt: str):
        return self.invoke_input(_text_input(adapter, prompt, "native"))

    def invoke_input(self, request):
        return self.kernel.invoke(request)
