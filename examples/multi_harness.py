import asyncio
import os
import sys
from omni_agent_invoke import Client, build_input


async def run(client, adapter):
    prompt = "Reply with OK without using tools."
    context = {
        "schema": "octo.context-envelope/v3",
        "items": [
            {
                "namespace": "octo.execution",
                "name": "adapter",
                "payload": {"type": "openclaw", "provider_agent_id": "main"},
            }
        ],
    }
    stream = (
        client.invoke_input(build_input([{"type":"text","text":prompt}], context, "canonical"))
        if adapter == "openclaw"
        else client.invoke(adapter, prompt)
    )
    async for frame in stream:
        print(adapter, frame)
        if frame.get("kind") == "control" and frame.get("control", {}).get("state") in (
            "failed",
            "cancelled",
            "lost",
        ):
            raise RuntimeError(f"{adapter} ended: {frame['control']['state']}")


async def main():
    if not sys.argv[1:]:
        raise SystemExit(
            "Usage: python examples/multi_harness.py codex claude-code openclaw dsh"
        )
    async with Client(os.environ["OCTO_KERNEL_ENDPOINT"]) as client:
        results = await asyncio.gather(
            *(run(client, adapter) for adapter in sys.argv[1:]), return_exceptions=True
        )
        failures = [
            str(result) for result in results if isinstance(result, BaseException)
        ]
        if failures:
            raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    asyncio.run(main())
