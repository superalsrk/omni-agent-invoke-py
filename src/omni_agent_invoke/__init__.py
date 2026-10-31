"""Native Python API for unified agent execution through Octo Runtime."""

from copy import deepcopy
from uuid import uuid4
import base64
import hashlib
from typing import Literal, TypedDict
from .kernel import KernelClient, KernelError, validate
from .protocol_generated import ProtocolMode as ProtocolModeLiteral


class ContextItem(TypedDict):
    namespace: str
    name: str
    payload: dict


class Context(TypedDict):
    schema: Literal["octo.context-envelope/v3"]
    items: list[ContextItem]


ContextEnvelope = Context
__all__ = [
    "Client",
    "KernelError",
    "Context",
    "ContextEnvelope",
    "ContextItem",
    "build_input",
    "image_input",
]


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
    adapter: str,
    prompt: str,
    mode: ProtocolModeLiteral = "canonical",
    context: Context | None = None,
) -> dict:
    if mode not in ("canonical", "native"):
        raise ValueError("mode must be canonical or native")
    items = [
        {
            "namespace": "octo.execution",
            "name": "adapter",
            "payload": {"type": adapter},
        },
        {
            "namespace": "octo.security",
            "name": "approval_policy",
            "payload": {"mode": "ask"},
        },
    ]
    if context is not None:
        if (
            not isinstance(context, dict)
            or set(context) != {"schema", "items"}
            or context["schema"] != "octo.context-envelope/v3"
            or not isinstance(context["items"], list)
        ):
            raise ValueError("Expected an octo.context-envelope/v3 Context envelope")
        seen = set()
        for item in context["items"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("namespace"), str)
                or not isinstance(item.get("name"), str)
            ):
                raise ValueError("Invalid Context item")
            key = (item["namespace"], item["name"])
            if key in seen:
                raise ValueError("Duplicate Context item")
            seen.add(key)
            if not isinstance(item.get("payload"), dict):
                raise ValueError("Context payload must be an object")
            if (
                key == ("octo.execution", "adapter")
                and item["payload"].get("type") != adapter
            ):
                raise ValueError("Context Adapter conflicts with adapter argument")
            items = [
                value for value in items if (value["namespace"], value["name"]) != key
            ]
            items.append(deepcopy(item))
    request = {
        "runId": str(uuid4()),
        "invocationId": str(uuid4()),
        "sessionId": str(uuid4()),
        "sessionGeneration": 0,
        "protocol_mode": mode,
        "inputs": [{"type": "text", "text": prompt}],
        "contexts": {"schema": "octo.context-envelope/v3", "items": items},
    }
    validate("InvokeInputWire", request)
    return request


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
        return self.invoke_input(build_input(adapter, prompt))

    def invoke_with_context(self, adapter: str, prompt: str, context: Context):
        return self.invoke_input(build_input(adapter, prompt, "canonical", context))

    def invoke_native(self, adapter: str, prompt: str):
        return self.invoke_input(build_input(adapter, prompt, "native"))

    def invoke_native_with_context(self, adapter: str, prompt: str, context: Context):
        return self.invoke_input(build_input(adapter, prompt, "native", context))

    def invoke_input(self, request):
        return self.kernel.invoke(request)
