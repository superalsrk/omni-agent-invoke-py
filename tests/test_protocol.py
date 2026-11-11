import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

from omni_agent_invoke import build_input, image_input
from omni_agent_invoke.kernel import KernelClient, KernelError, response

REF = dict(
    kernel_instance_id="kernel",
    run_id="run",
    invocation_id="invoke",
    agent_session_id="session",
    session_generation=0,
    stream_id="stream",
    protocol_mode="canonical",
    protocol="test/v1",
)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="omni-py-", dir="/tmp")
        self.endpoint = str(Path(self.directory.name) / "k.sock")
        self.calls = []
        self.handler = None
        self.tasks = set()

        async def serve(reader, writer):
            task = asyncio.current_task()
            self.tasks.add(task)
            try:
                request = json.loads(await reader.readline())
                self.calls.append(request["method"])
                await self.handler(writer, request)
            finally:
                writer.close()
                await writer.wait_closed()
                self.tasks.remove(task)

        self.server = await asyncio.start_unix_server(serve, self.endpoint)
        self.client = KernelClient(self.endpoint)

    async def asyncTearDown(self):
        await self.client.close()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*self.tasks)
        self.directory.cleanup()

    async def reply(self, writer, request, result):
        data = (
            json.dumps(dict(jsonrpc="2.0", id=request["id"], result=result)).encode()
            + b"\n"
        )
        writer.write(data[:9])
        await writer.drain()
        await asyncio.sleep(0)
        writer.write(data[9:])
        await writer.drain()

    async def test_lost_ack_queries_original_run_without_reinvoking(self):
        ref = copy.deepcopy(REF)

        async def handler(writer, request):
            if request["method"] == "status":
                await self.reply(
                    writer, request, dict(ipc_version=2, kernel_instance_id="kernel")
                )
            elif request["method"] == "agent_run.invoke":
                input = request["params"]["input"]
                ref.update(
                    run_id=input["runId"],
                    invocation_id=input["invocationId"],
                    agent_session_id=input["sessionId"],
                )
                # Accepted execution, transport closes before receipt.
            elif request["method"] == "agent_run.get":
                self.assertEqual(request["params"]["key"]["run_id"], ref["run_id"])
                await self.reply(
                    writer, request, dict(ref=ref, oldest_seq=1, latest_seq=0)
                )

        self.handler = handler
        input = build_input([{"type":"text","text":"hello"}], {"schema":"octo.context-envelope/v3","items":[]}, "canonical")
        result = await self.client.submit(input)
        self.assertEqual(result["run_id"], input["runId"])
        self.assertEqual(self.calls, ["status", "agent_run.invoke", "agent_run.get"])

    async def stream_case(self, scenario):
        async def handler(writer, request):
            await self.reply(writer, request, dict(ref=REF, oldest_seq=1, latest_seq=1))
            frame = {
                key: value for key, value in REF.items() if key != "kernel_instance_id"
            }
            frame.update(
                seq=1, kind="control", control=dict(type="state", state="completed")
            )
            params = dict(
                kernel_instance_id="kernel",
                run_id="run",
                stream_id="stream",
                seq=1,
                event=frame,
            )
            if scenario == "gap":
                params["seq"] = frame["seq"] = 2
            elif scenario == "identity":
                frame["invocation_id"] = "other"
            elif scenario == "instance":
                params["kernel_instance_id"] = "other"
            writer.write(
                json.dumps(
                    dict(jsonrpc="2.0", method="agent_run.event", params=params)
                ).encode()
                + b"\n"
            )
            await writer.drain()

        self.handler = handler
        return [frame async for frame in self.client.subscribe(REF)]

    async def test_fragmented_terminal_stream(self):
        frames = await self.stream_case("terminal")
        self.assertEqual(frames[-1]["control"]["state"], "completed")

    async def test_sequence_gap_fails(self):
        with self.assertRaisesRegex(KernelError, "STREAM_GAP"):
            await self.stream_case("gap")

    async def test_changed_run_identity_fails(self):
        with self.assertRaisesRegex(KernelError, "RUN_IDENTITY_MISMATCH"):
            await self.stream_case("identity")

    async def test_changed_kernel_instance_fails(self):
        with self.assertRaisesRegex(KernelError, "KERNEL_INSTANCE_CHANGED"):
            await self.stream_case("instance")

    async def test_lost_cancel_ack_is_unknown_and_never_retried(self):
        async def handler(writer, request):
            pass

        self.handler = handler
        with self.assertRaisesRegex(KernelError, "OPERATION_OUTCOME_UNKNOWN"):
            await self.client.cancel(REF, "test")
        self.assertEqual(self.calls, ["agent_run.cancel"])


class DataTests(unittest.TestCase):
    def test_image_hash_encoding_and_limits(self):
        image = image_input(b"abc", "image/png")
        self.assertEqual(image["data"], "YWJj")
        self.assertEqual(image["byteSize"], 3)
        self.assertEqual(
            image["sha256"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        for data, mime in [
            (b"", "image/png"),
            (b"x" * 2097153, "image/png"),
            (b"x", "image/gif"),
        ]:
            with self.assertRaises(ValueError):
                image_input(data, mime)

    def test_response_id_and_exclusive_result(self):
        for value in [
            dict(jsonrpc="2.0", id="wrong", result={}),
            dict(jsonrpc="2.0", id="id", result={}, error={}),
        ]:
            with self.assertRaisesRegex(KernelError, "INVALID_RESPONSE"):
                response(value, "id")
