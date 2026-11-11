import argparse
import asyncio
import json
import mimetypes
import os
from pathlib import Path
from omni_agent_invoke import Client, AgentEnv, build_input, image_input
from omni_agent_invoke.kernel import terminal


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    agent_env: AgentEnv = {
        "schema": "octo.context-envelope/v3",
        "items": [
            {"namespace": "octo.execution", "name": "adapter", "payload": {"type": "codex"}},
            {
                "namespace": "octo.execution",
                "name": "limits",
                "payload": {"run_timeout_ms": 60000},
            },
        ],
    }
    request = build_input(
        [{"type": "text", "text": "This is a Python input construction example."},
         {"type": "text", "text": "Reply with OK without using tools."}],
        agent_env,
        "native" if args.native else "canonical",
    )
    if args.image:
        request["inputs"].append(
            image_input(
                Path(args.image).read_bytes(), mimetypes.guess_type(args.image)[0]
            )
        )
    if args.dry_run:
        print(json.dumps(request, indent=2))
        return
    async with Client(os.environ["OCTO_KERNEL_ENDPOINT"]) as client:
        async for frame in client.invoke_input(request):
            print(json.dumps(frame))
            if state := terminal(frame):
                if state != "completed":
                    raise RuntimeError("Execution ended: " + state)


if __name__ == "__main__":
    asyncio.run(main())
