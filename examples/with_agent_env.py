import asyncio
import json
import os
from omni_agent_invoke import Client, AgentEnv, build_input
from omni_agent_invoke.kernel import terminal


async def main():
    agent_env: AgentEnv = {
        "schema": "octo.context-envelope/v3",
        "items": [
            {
                "namespace": "octo.execution",
                "name": "adapter",
                "payload": {
                    "type": "codex"
                },
            }
        ],
    }
    async with Client(os.environ["OCTO_KERNEL_ENDPOINT"]) as client:
        async for frame in client.invoke_input(build_input(
            [{"type": "text", "text": "The caller is a Python application."},
             {"type": "text", "text": "Reply with OK."}], agent_env, "canonical"
        )):
            print(json.dumps(frame))
            if state := terminal(frame):
                if state != "completed":
                    raise RuntimeError("Execution ended: " + state)


asyncio.run(main())
