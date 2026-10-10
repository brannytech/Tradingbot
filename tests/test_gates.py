import json
import tempfile
import unittest
from pathlib import Path
from tradingbot.gates import gate_records,source_hash


class GateTests(unittest.TestCase):
    def test_source_change_invalidates_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"gates.json"
            p.write_text(json.dumps([dict(id=0,title="baseline",status="PASS",source_hash="old",known_issues=[])]))
            rows=gate_records(p)
            self.assertEqual(rows[0]["status"],"BLOCKED")
            self.assertFalse(rows[0]["progression_allowed"])

    def test_prerequisite_failure_and_live_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"gates.json"
            p.write_text(json.dumps([dict(id=1,title="foundation",status="PASS",source_hash=source_hash(),known_issues=[])]))
            rows=gate_records(p)
            self.assertEqual(rows[1]["status"],"BLOCKED")
            self.assertEqual(rows[12]["status"],"LOCKED")
