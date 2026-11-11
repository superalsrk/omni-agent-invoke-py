"""Independent, MIT-licensed implementation of Octo Kernel IPC v2."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from uuid import uuid4
from .protocol_generated import RunRef, LookupKey, METHODS

MAX_REQUEST = 33_554_432
MAX_LINE = 42_008_576
FIELDS = (
    "run_id",
    "invocation_id",
    "stream_id",
    "agent_session_id",
    "session_generation",
    "protocol_mode",
    "protocol",
)
INPUT_FIELDS = dict(
    zip(
        (
            "run_id",
            "invocation_id",
            "agent_session_id",
            "session_generation",
            "protocol_mode",
        ),
        ("runId", "invocationId", "sessionId", "sessionGeneration", "protocol_mode"),
    )
)


class KernelError(Exception):
    def __init__(self, code, data=None, *, remote=False):
        self.code, self.data, self.remote = code, data, remote
        super().__init__(code)


def validate(_definition, request):
    if (
        request.get("protocol_mode") not in ("canonical", "native")
        or not isinstance(request.get("inputs"), list)
        or not request["inputs"]
    ):
        raise KernelError("INVALID_INPUT")
    if "contexts" in request or "controlInstructions" in request:
        raise KernelError("INVALID_INPUT")
    context = request.get("agentEnv")
    if (
        not isinstance(context, dict)
        or set(context) != {"schema", "items"}
        or context["schema"] != "octo.context-envelope/v3"
        or not isinstance(context["items"], list)
    ):
        raise KernelError("INVALID_CONTEXT")
    seen = set()
    for item in context["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
            raise KernelError("INVALID_CONTEXT")
        key = (item.get("namespace"), item.get("name"))
        if key == ("octo.control", "instructions"):
            raise KernelError("CONTROL_INSTRUCTIONS_REMOVED")
        if any(not isinstance(value, str) or not value for value in key) or key in seen:
            raise KernelError("INVALID_CONTEXT")
        seen.add(key)
    if len(seen) > 32 or len(json.dumps(context, ensure_ascii=False).encode()) > 65_536:
        raise KernelError("INVALID_CONTEXT")


def terminal(frame):
    control = frame.get("control", {})
    state = (
        control.get("state")
        if frame.get("kind") == "control" and control.get("type") == "state"
        else None
    )
    return state if state in ("completed", "failed", "cancelled", "lost") else None


def identity(actual, expected, fields=FIELDS):
    if actual.get("kernel_instance_id") != expected.get("kernel_instance_id"):
        raise KernelError("KERNEL_INSTANCE_CHANGED")
    if any(actual.get(key) != expected.get(key) for key in fields):
        raise KernelError("RUN_IDENTITY_MISMATCH")


def check_ref(ref):
    if not isinstance(ref, dict) or any(
        not isinstance(ref.get(key), str) or not ref[key]
        for key in (*FIELDS[:4], "protocol", "kernel_instance_id")
    ):
        raise KernelError("INVALID_RESPONSE")
    generation = ref.get("session_generation")
    if (
        type(generation) is not int
        or not 0 <= generation <= 9_007_199_254_740_991
        or ref.get("protocol_mode") not in ("canonical", "native")
    ):
        raise KernelError("INVALID_RESPONSE")


def snapshot(value, ref=None):
    if not isinstance(value, dict):
        raise KernelError("INVALID_RESPONSE")
    check_ref(value.get("ref"))
    if ref is not None:
        identity(value["ref"], ref)
    oldest, latest = value.get("oldest_seq"), value.get("latest_seq")
    if (
        type(oldest) is not int
        or type(latest) is not int
        or not 1 <= oldest <= latest + 1
        or not 0 <= latest <= 9_007_199_254_740_991
    ):
        raise KernelError("INVALID_RESPONSE")
    if "terminal" in value:
        check_frame(value["terminal"], value["ref"])
        if (
            terminal(value["terminal"]) is None
            or value["terminal"].get("seq") != latest
        ):
            raise KernelError("INVALID_RESPONSE")
    return value


def check_frame(frame, ref):
    if not isinstance(frame, dict) or any(
        frame.get(key) != ref.get(key) for key in FIELDS
    ):
        raise KernelError("RUN_IDENTITY_MISMATCH")
    if (
        type(frame.get("seq")) is not int
        or not 1 <= frame["seq"] <= 9_007_199_254_740_991
    ):
        raise KernelError("STREAM_GAP")
    kind = frame.get("kind")
    if kind not in ("canonical", "native", "control") or not isinstance(
        frame.get(
            {"canonical": "event", "native": "payload", "control": "control"}[kind]
        ),
        dict,
    ):
        raise KernelError("HOST_FRAME_INVALID")
    if kind != "control" and kind != ref["protocol_mode"]:
        raise KernelError("HOST_FRAME_INVALID")


async def read_line(reader):
    try:
        line = await reader.readline()
    except ValueError as error:
        raise KernelError("RESPONSE_TOO_LARGE") from error
    if not line or not line.endswith(b"\n"):
        raise KernelError("CONNECTION_CLOSED")
    if len(line) > MAX_LINE:
        raise KernelError("RESPONSE_TOO_LARGE")
    try:
        return json.loads(
            line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
    except (ValueError, UnicodeError) as error:
        raise KernelError("INVALID_RESPONSE") from error


def response(value, request_id):
    if (
        not isinstance(value, dict)
        or value.get("jsonrpc") != "2.0"
        or value.get("id") != request_id
        or ("result" in value) == ("error" in value)
    ):
        raise KernelError("INVALID_RESPONSE")
    if "error" in value:
        error = value["error"]
        if (
            not isinstance(error, dict)
            or not isinstance(error.get("data"), dict)
            or not isinstance(error["data"].get("code"), str)
        ):
            raise KernelError("INVALID_RESPONSE")
        raise KernelError(error["data"]["code"], error["data"], remote=True)
    return value["result"]


def request(method, params):
    request_id = str(uuid4())
    line = (
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )
    if len(line) > MAX_REQUEST:
        raise KernelError("INVOKE_REQUEST_TOO_LARGE")
    return request_id, line


class KernelClient:
    def __init__(self, endpoint):
        self.endpoint, self.closed = endpoint, False
        self._writers = set()
        self._slots = asyncio.Semaphore(32)

    @asynccontextmanager
    async def _channel(self):
        writer = None
        await asyncio.wait_for(self._slots.acquire(), 5)
        try:
            if self.closed:
                raise KernelError("CLIENT_CLOSED")
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.endpoint, limit=MAX_LINE), 5
            )
            self._writers.add(writer)
            yield reader, writer
        finally:
            if writer is not None:
                self._writers.discard(writer)
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 1)
                except (OSError, TimeoutError):
                    pass
            self._slots.release()

    async def close(self):
        self.closed = True
        for writer in tuple(self._writers):
            writer.close()
        await asyncio.gather(
            *(writer.wait_closed() for writer in tuple(self._writers)),
            return_exceptions=True,
        )

    async def _rpc(self, method, params, side_effect=False):
        request_id, line = request(method, params)
        attempted = False
        try:
            async with self._channel() as (reader, writer):
                async with asyncio.timeout(30 if method == "agent_run.invoke" else 5):
                    attempted = True
                    writer.write(line)
                    await writer.drain()
                    return response(await read_line(reader), request_id)
        except (OSError, TimeoutError, KernelError) as error:
            if isinstance(error, KernelError) and error.remote:
                raise
            if side_effect and attempted:
                raise KernelError(
                    "OPERATION_OUTCOME_UNKNOWN", {"cause": str(error)}
                ) from error
            if isinstance(error, KernelError):
                raise
            raise KernelError(
                "KERNEL_TIMEOUT"
                if isinstance(error, TimeoutError)
                else "KERNEL_UNAVAILABLE"
            ) from error

    async def status(self):
        value = await self._rpc(METHODS["status"], {})
        if (
            not isinstance(value, dict)
            or value.get("ipc_version") != 2
            or not value.get("kernel_instance_id")
        ):
            raise KernelError("INVALID_RESPONSE")
        return value

    async def list(self):
        result = await self._rpc("adapter.list", {})
        if not isinstance(result, list):
            raise KernelError("INVALID_RESPONSE")
        return result

    async def get(self, key: LookupKey, expected_instance=None):
        params = {"key": key}
        if expected_instance:
            params["kernel_instance_id"] = expected_instance
        value = snapshot(await self._rpc("agent_run.get", params))
        if any(value["ref"].get(field) != item for field, item in key.items()):
            raise KernelError("RUN_IDENTITY_MISMATCH")
        if (
            expected_instance
            and value["ref"]["kernel_instance_id"] != expected_instance
        ):
            raise KernelError("KERNEL_INSTANCE_CHANGED")
        return value

    async def submit(self, input):
        input = copy.deepcopy(input)
        for field in ("runId", "invocationId", "sessionId"):
            input.setdefault(field, str(uuid4()))
        input.setdefault("sessionGeneration", 0)
        input.setdefault("protocol_mode", "native")
        validate("InvokeInputWire", input)
        key = {field: input[source] for field, source in INPUT_FIELDS.items()}
        instance = (await self.status())["kernel_instance_id"]
        try:
            result = await self._rpc(
                "agent_run.invoke",
                {"input": input, "kernel_instance_id": instance},
                True,
            )
            if not isinstance(result, dict) or not isinstance(
                result.get("receipt"), dict
            ):
                raise KernelError("INVALID_RESPONSE")
            ref = {
                **result["receipt"],
                "kernel_instance_id": result.get("kernel_instance_id"),
            }
            check_ref(ref)
            if ref["kernel_instance_id"] != instance or any(
                ref.get(field) != value for field, value in key.items()
            ):
                raise KernelError("RUN_IDENTITY_MISMATCH")
            return ref
        except KernelError as error:
            if error.remote or error.code not in (
                "OPERATION_OUTCOME_UNKNOWN",
                "INVALID_RESPONSE",
                "RUN_IDENTITY_MISMATCH",
            ):
                raise
            try:
                async with asyncio.timeout(10):
                    for delay in (0.1, 0.25, 0.5):
                        await asyncio.sleep(delay)
                        try:
                            return (await self.get(key, instance))["ref"]
                        except KernelError as lookup_error:
                            if lookup_error.code in (
                                "KERNEL_INSTANCE_CHANGED",
                                "RUN_IDENTITY_MISMATCH",
                            ):
                                raise
            except TimeoutError:
                pass
            raise KernelError(
                "RUN_OUTCOME_UNKNOWN", {"key": key, "kernel_instance_id": instance}
            ) from error

    async def cancel(self, ref, reason=None):
        result = await self._rpc(
            "agent_run.cancel",
            {"ref": ref, **({"reason": reason} if reason else {})},
            True,
        )
        if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
            raise KernelError("OPERATION_OUTCOME_UNKNOWN")
        return result

    async def respond(self, ref, answer):
        return await self._rpc(
            "agent_run.respond", {"ref": ref, "response": answer}, True
        )

    async def respond_native(self, ref, answer):
        return await self._rpc(
            "agent_run.native.respond", {"ref": ref, "response": answer}, True
        )

    async def subscribe(self, ref: RunRef, after_seq=0):
        check_ref(ref)
        if type(after_seq) is not int or not 0 <= after_seq <= 9_007_199_254_740_991:
            raise KernelError("INVALID_CURSOR")
        attempts, started = 0, None
        while True:
            try:
                async with self._channel() as (reader, writer):
                    request_id, line = request(
                        "agent_run.subscribe", {"ref": ref, "after_seq": after_seq}
                    )
                    async with asyncio.timeout(5):
                        writer.write(line)
                        await writer.drain()
                        state = snapshot(
                            response(await read_line(reader), request_id), ref
                        )
                    if after_seq > state["latest_seq"]:
                        raise KernelError("INVALID_CURSOR")
                    if after_seq + 1 < state["oldest_seq"]:
                        raise KernelError("STREAM_GAP")
                    if "terminal" in state and after_seq == state["latest_seq"]:
                        return
                    while True:
                        notification = await read_line(reader)
                        if (
                            not isinstance(notification, dict)
                            or notification.get("jsonrpc") != "2.0"
                            or "id" in notification
                        ):
                            raise KernelError("HOST_FRAME_INVALID")
                        params = notification.get("params", {})
                        if (
                            params.get("kernel_instance_id")
                            != ref["kernel_instance_id"]
                        ):
                            raise KernelError("KERNEL_INSTANCE_CHANGED")
                        if notification.get("method") == "agent_run.stream_error":
                            raise KernelError(params.get("code", "INVALID_RESPONSE"))
                        if (
                            notification.get("method") != "agent_run.event"
                            or params.get("run_id") != ref["run_id"]
                            or params.get("stream_id") != ref["stream_id"]
                        ):
                            raise KernelError("RUN_IDENTITY_MISMATCH")
                        frame = params.get("event")
                        check_frame(frame, ref)
                        if (
                            frame["seq"] != after_seq + 1
                            or params.get("seq") != frame["seq"]
                        ):
                            raise KernelError("STREAM_GAP")
                        after_seq = frame["seq"]
                        attempts, started = 0, None
                        yield frame
                        if terminal(frame):
                            return
            except (OSError, TimeoutError, KernelError) as error:
                retryable = not isinstance(error, KernelError) or error.code in (
                    "CONNECTION_CLOSED",
                    "KERNEL_UNAVAILABLE",
                    "KERNEL_TIMEOUT",
                )
                now = asyncio.get_running_loop().time()
                started = now if started is None else started
                if not retryable or attempts >= 3 or now - started >= 10 or self.closed:
                    raise
                await asyncio.sleep((0.1, 0.25, 0.5)[attempts])
                attempts += 1

    async def invoke(self, input):
        ref = await self.submit(input)
        async for frame in self.subscribe(ref):
            yield frame
