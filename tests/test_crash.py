import tempfile
import unittest
from pathlib import Path

from sparky.crash import analyze_crash


class CrashParserTests(unittest.TestCase):
    def test_mesh_signature_becomes_high_confidence_finding(self):
        sample = """Unhandled exception EXCEPTION_ACCESS_VIOLATION at SkyrimSE.exe+123
BSResourceNiBinaryStream
NiNode
NiStringExtraData
data\\MESHES\\actors\\character\\sample.nif
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crash.log"
            path.write_text(sample)
            report = analyze_crash(path)
            self.assertEqual(report.findings[0].confidence, "High")
            self.assertIn("sample.nif", report.assets[0])


if __name__ == "__main__":
    unittest.main()
