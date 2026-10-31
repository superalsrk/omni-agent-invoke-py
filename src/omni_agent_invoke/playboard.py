"""Independent CLI for an existing Octo Runtime Kernel. Output is NDJSON."""

import argparse
import asyncio
import json
import os
import signal
import sys
from . import Client, build_input
from .kernel import terminal


def load(path):
    file = sys.stdin.buffer if path == "-" else open(path, "rb")
    try:
        data = file.read(33_554_433)
        if len(data) > 33_554_432:
            raise ValueError("JSON exceeds 32 MiB")
        return json.loads(data)
    finally:
        if file is not sys.stdin.buffer:
            file.close()


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


async def run(args):
    async with Client(args.endpoint) as client:
        kernel = client.kernel
        if args.command in ("status", "list"):
            emit(await getattr(kernel, args.command)())
            return 0
        if args.command in ("submit", "playboard"):
            if args.prompt is not None:
                request = build_input(
                    args.adapter,
                    args.prompt,
                    args.mode,
                    load(args.context) if args.context else None,
                )
            else:
                if args.context:
                    raise ValueError("--context requires --prompt")
                request = load(args.request)
            ref = await kernel.submit(request)
            print(json.dumps({"ref": ref}), file=sys.stderr)
            if args.receipt:
                descriptor = os.open(
                    args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "w") as file:
                    json.dump(ref, file)
            if args.command == "submit":
                emit(ref)
                return 0
        else:
            ref = load(args.ref)
        if args.command == "get":
            emit(
                await kernel.get(
                    {
                        key: ref[key]
                        for key in (
                            "run_id",
                            "invocation_id",
                            "agent_session_id",
                            "session_generation",
                            "protocol_mode",
                        )
                    },
                    ref["kernel_instance_id"],
                )
            )
            return 0
        if args.command == "cancel":
            emit(await kernel.cancel(ref, args.reason))
            return 0
        if args.command in ("respond", "native-respond"):
            method = (
                kernel.respond if args.command == "respond" else kernel.respond_native
            )
            emit(await method(ref, load(args.response)))
            return 0
        stream = kernel.subscribe(ref, args.after)
        interrupted = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, interrupted.set)
        stop_task = asyncio.create_task(interrupted.wait())
        pending = None
        deadline = loop.time() + args.timeout if args.timeout else None
        exit_code = 0
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(stream))
                remaining = (
                    max(0, deadline - loop.time()) if deadline is not None else None
                )
                done, _ = await asyncio.wait(
                    [pending] + ([stop_task] if not exit_code else []),
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done or (stop_task in done and not exit_code):
                    if exit_code:
                        raise RuntimeError(
                            "Cancellation unresolved; retain the original receipt"
                        )
                    exit_code = 130 if stop_task in done else 124
                    if args.command == "subscribe":
                        return exit_code
                    try:
                        print(
                            json.dumps(
                                {
                                    "cancel": await kernel.cancel(
                                        ref, "playboard_interrupted"
                                    )
                                }
                            ),
                            file=sys.stderr,
                        )
                    except Exception as error:
                        print(f"Cancellation outcome unknown: {error}", file=sys.stderr)
                    deadline = loop.time() + 10
                    continue
                try:
                    frame = pending.result()
                except StopAsyncIteration:
                    return exit_code
                pending = None
                emit(frame)
                if state := terminal(frame):
                    return exit_code or (0 if state == "completed" else 1)
        finally:
            loop.remove_signal_handler(signal.SIGINT)
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            await stream.aclose()


def main():
    parser = argparse.ArgumentParser(
        description="Invoke Codex, Claude Code, OpenClaw and DSH through Octo Runtime"
    )
    parser.add_argument(
        "command",
        choices=[
            "status",
            "list",
            "playboard",
            "submit",
            "get",
            "subscribe",
            "cancel",
            "respond",
            "native-respond",
        ],
    )
    parser.add_argument("--endpoint", default=os.environ.get("OCTO_KERNEL_ENDPOINT"))
    parser.add_argument("--adapter", default="codex")
    parser.add_argument("--mode", choices=["canonical", "native"], default="canonical")
    for name, default in [
        ("prompt", None),
        ("context", None),
        ("receipt", None),
        ("ref", None),
        ("reason", "playboard_user_cancelled"),
        ("response", "-"),
        ("request", "-"),
    ]:
        parser.add_argument("--" + name, default=default)
    parser.add_argument("--after", type=int, default=0)
    parser.add_argument(
        "--timeout", type=float, default=0, help="execution deadline in seconds"
    )
    args = parser.parse_args()
    if not args.endpoint or args.timeout < 0 or args.after < 0:
        parser.error("Set an existing Kernel endpoint and nonnegative timeout/cursor")
    try:
        code = asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        print(str(error), file=sys.stderr)
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
