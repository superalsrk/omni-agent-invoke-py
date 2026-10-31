import copy
import unittest
from unittest.mock import Mock
from omni_agent_invoke import Client, build_input


class ApiTests(unittest.TestCase):
    def test_all_four_signatures_select_mode_and_preserve_context(self):
        context = {
            "schema": "octo.context-envelope/v3",
            "items": [
                {
                    "namespace": "octo.content",
                    "name": "inline",
                    "payload": {"entries": [{"text": "background"}]},
                }
            ],
        }
        original = copy.deepcopy(context)
        client = Client("unused.sock")
        client.kernel.invoke = Mock(return_value="stream")
        for name, mode, supplied in [
            ("invoke", "canonical", False),
            ("invoke_with_context", "canonical", True),
            ("invoke_native", "native", False),
            ("invoke_native_with_context", "native", True),
        ]:
            with self.subTest(name=name):
                args = ("codex", "hello", context) if supplied else ("codex", "hello")
                self.assertEqual(getattr(client, name)(*args), "stream")
                request = client.kernel.invoke.call_args.args[0]
                self.assertEqual(request["protocol_mode"], mode)
                self.assertEqual(
                    len(request["contexts"]["items"]), 3 if supplied else 2
                )
                self.assertNotEqual(request["runId"], request["invocationId"])
        self.assertEqual(context, original)

    def test_conflicts_duplicates_and_invalid_mode_fail(self):
        item = {
            "namespace": "octo.execution",
            "name": "adapter",
            "payload": {"type": "openclaw"},
        }
        with self.assertRaises(ValueError):
            build_input(
                "codex",
                "hello",
                context={"schema": "octo.context-envelope/v3", "items": [item]},
            )
        with self.assertRaises(ValueError):
            build_input(
                "openclaw",
                "hello",
                context={"schema": "octo.context-envelope/v3", "items": [item, item]},
            )
        with self.assertRaises(ValueError):
            build_input("codex", "hello", "invalid")

    def test_openclaw_agent_and_explicit_policy_survive(self):
        context = {
            "schema": "octo.context-envelope/v3",
            "items": [
                {
                    "namespace": "octo.execution",
                    "name": "adapter",
                    "payload": {"type": "openclaw", "provider_agent_id": "main"},
                },
                {
                    "namespace": "octo.security",
                    "name": "approval_policy",
                    "payload": {"mode": "assisted"},
                },
            ],
        }
        self.assertEqual(
            build_input("openclaw", "hello", context=context)["contexts"], context
        )
