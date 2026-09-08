"""The emulator must relax one socket family without relaxing other policy."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "android_emulator", Path(__file__).resolve().parents[1] / "tools/android_emulator.py"
)
assert SPEC is not None and SPEC.loader is not None
emulator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emulator)


class VsockPolicyTests(unittest.TestCase):
    def setUp(self):
        self.refusal = {
            "names": ["socket"],
            "action": "SCMP_ACT_ERRNO",
            "args": [{"index": 0, "value": 40, "valueTwo": 0, "op": "SCMP_CMP_EQ"}],
            "errnoRet": 1,
            "errno": "EPERM",
        }

    def test_preserves_unrelated_policy_and_input(self):
        unrelated = {"names": ["mount"], "action": "SCMP_ACT_ERRNO"}
        original = {"defaultAction": "SCMP_ACT_ERRNO", "syscalls": [self.refusal, unrelated]}
        result = emulator.allow_vsock(original)
        self.assertEqual(result["defaultAction"], original["defaultAction"])
        self.assertEqual(result["syscalls"][1], unrelated)
        self.assertEqual(result["syscalls"][0]["action"], "SCMP_ACT_ALLOW")
        self.assertNotIn("errno", result["syscalls"][0])
        self.assertNotIn("errnoRet", result["syscalls"][0])
        self.assertEqual(original["syscalls"][0]["action"], "SCMP_ACT_ERRNO")

    def test_refuses_missing_or_ambiguous_rule(self):
        for rules in ([], [self.refusal, self.refusal]):
            with self.subTest(rules=len(rules)), self.assertRaisesRegex(ValueError, "found"):
                emulator.allow_vsock({"syscalls": rules})

    def test_does_not_relax_a_broader_socket_rule(self):
        self.refusal["names"].append("socketpair")
        with self.assertRaisesRegex(ValueError, "found 0"):
            emulator.allow_vsock({"syscalls": [self.refusal]})


if __name__ == "__main__":
    unittest.main()
