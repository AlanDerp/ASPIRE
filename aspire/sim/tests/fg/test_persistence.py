from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.factual_grounding.persistence import FGStore


class PersistenceTests(unittest.TestCase):
    def test_public_private_are_disjoint_and_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = FGStore(root / "public", root / "private")
            store.append_public("fg/events.jsonl", {"id": 1})
            store.append_public("fg/events.jsonl", {"id": 2})
            store.append_private("fg/audit.jsonl", {"secret": True})
            self.assertEqual([x["id"] for x in FGStore.read(root / "public/fg/events.jsonl")], [1, 2])
            self.assertFalse((root / "public/fg/audit.jsonl").exists())
            with self.assertRaises(ValueError): store.append_public("../escape", {})


if __name__ == "__main__": unittest.main()
