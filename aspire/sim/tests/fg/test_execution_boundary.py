from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.agent_protocol.safety import validate_public_python
from aspire.sim.cap.envs.generated_worker import execute_isolated_python


class ExecutionBoundaryTests(unittest.TestCase):
    def test_public_helpers_are_allowed(self):
        validate_public_python("obs = get_observation()\nmove_to_joints([0, 1])")

    def test_private_names_and_attributes_are_rejected(self):
        for code in (
            "env.reset()", "APIS['x']", "x.sim.data", "x._eval_predicate()",
            "open('/tmp/x')", "import os", "x.__class__.__base__",
            "getattr(x, 'sim')", "globals()",
        ):
            with self.assertRaises(ValueError):
                validate_public_python(code)

    @unittest.skipUnless(
        os.environ.get("ASPIRE_OS_SANDBOX_TEST") == "1",
        "set ASPIRE_OS_SANDBOX_TEST=1 outside the enclosing file sandbox",
    )
    def test_real_worker_can_call_public_rpc_but_cannot_read_private_root(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            secret = private / "audit.txt"
            secret.write_text("41")
            code = (
                "public_value = add(2, 3)\n"
                "try:\n"
                f"    leaked = np.loadtxt({str(secret)!r})\n"
                "    RESULT = [public_value, str(leaked)]\n"
                "except Exception:\n"
                "    RESULT = [public_value, 'blocked']\n"
            )
            result = execute_isolated_python(
                code, {"visible": True}, {"add": lambda left, right: left + right},
                private_root=private, timeout_seconds=10,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"], [5, "blocked"])


if __name__ == "__main__": unittest.main()
