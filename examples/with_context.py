import asyncio
import json
import os
from omni_agent_invoke import Client, Context
from omni_agent_invoke.kernel import terminal


async def main():
    context: Context = {
        "schema": "octo.context-envelope/v3",
        "items": [
            {
                "namespace": "octo.content",
                "name": "inline",
                "payload": {
                    "entries": [{"text": "The caller is a Python application."}]
                },
            }
        ],
    }
    async with Client(os.environ["OCTO_KERNEL_ENDPOINT"]) as client:
        # invoke_native_with_context selects Provider-native output instead.
        async for frame in client.invoke_with_context(
            "codex", "Reply with OK.", context
        ):
            print(json.dumps(frame))
            if state := terminal(frame):
                if state != "completed":
                    raise RuntimeError("Execution ended: " + state)


asyncio.run(main())
