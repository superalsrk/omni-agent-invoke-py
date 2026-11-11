import copy
import unittest
from unittest.mock import Mock
from omni_agent_invoke import Client, build_input, image_input
from omni_agent_invoke.kernel import KernelError, validate


class ApiTests(unittest.TestCase):
    def test_complete_parts_and_environment_pass_through(self):
        parts = [{"type": "text", "text": "Application instructions and history"},
                 image_input(b"abc", "image/png"),
                 {"type": "text", "text": "Current question"}]
        env = {"schema": "octo.context-envelope/v3", "items": [
            {"namespace": "private.host", "name": "config", "payload": {"nested": [1, True]}},
            {"namespace": "octo.execution", "name": "adapter",
             "payload": {"type": "openclaw", "provider_agent_id": "main"}}]}
        original = copy.deepcopy((parts, env))
        client = Client("unused.sock")
        client.kernel.invoke = Mock(return_value="stream")
        for mode in ("canonical", "native"):
            request = build_input(parts, env, mode)
            self.assertEqual(client.invoke_input(request), "stream")
            self.assertEqual(request["inputs"], parts)
            self.assertEqual(request["agentEnv"], env)
            self.assertNotIn("contexts", request)
            request["agentEnv"]["items"].clear()
            request["inputs"].clear()
        self.assertEqual((parts, env), original)

    def test_empty_environment_and_native_default(self):
        request = build_input([{"type": "text", "text": "hello"}],
                              {"schema": "octo.context-envelope/v3", "items": []})
        self.assertEqual(request["agentEnv"]["items"], [])
        self.assertEqual(request["protocol_mode"], "native")

    def test_removed_contract_is_rejected(self):
        request = build_input([{"type": "text", "text": "hello"}],
                              {"schema": "octo.context-envelope/v3", "items": []})
        request["contexts"] = request["agentEnv"]
        with self.assertRaises(KernelError):
            validate("InvokeInputWire", request)
        del request["contexts"]
        request["agentEnv"]["items"].append(
            {"namespace": "octo.control", "name": "instructions", "payload": {}})
        with self.assertRaises(KernelError):
            validate("InvokeInputWire", request)
