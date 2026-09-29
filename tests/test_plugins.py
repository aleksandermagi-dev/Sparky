import struct
import tempfile
import unittest
from pathlib import Path

from sparky.plugins import BUILTIN_FULL_PLUGINS, TES4_LIGHT, assess_load_order, parse_plugin


def make_plugin(path: Path, flags=0, masters=(), records=(b"ARMO",)):
    for master in masters:
        (path.parent / master).touch(exist_ok=True)
    subs = b"HEDR" + struct.pack("<HfII", 12, 1.7, len(records), 0x800)
    subs += b"".join(b"MAST" + struct.pack("<H", len(m) + 1) + m.encode() + b"\0" + b"DATA" + struct.pack("<H", 8) + b"\0" * 8 for m in masters)
    tes4 = b"TES4" + struct.pack("<I", len(subs)) + struct.pack("<I", flags) + b"\0" * 12 + subs
    groups = b""
    for sig in records:
        record = sig + struct.pack("<IIIII", 0, 0, 0x00001234, 0, 0)
        groups += b"GRUP" + struct.pack("<I", 24 + len(record)) + sig + b"\0" * 12 + record
    path.write_bytes(tes4 + groups)


class PluginParserTests(unittest.TestCase):
    def test_override_patch_with_archive_and_dependents_can_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_plugin(root / 'world patch.esp', masters=('Skyrim.esm',), records=(b'CELL', b'REFR'))
            (root / 'world patch.bsa').touch()
            make_plugin(root / 'dependent.esp', masters=('Skyrim.esm', 'world patch.esp'))
            assessment = assess_load_order(root, ['world patch.esp', 'dependent.esp']).assessments[0]
            self.assertTrue(assessment.esl_ready)
            self.assertFalse(assessment.merge_ready)
            (root / 'Skyrim.esm').unlink()
            self.assertFalse(assess_load_order(root, ['world patch.esp']).assessments[0].esl_ready)

    def test_esl_override_types_are_independent_of_merge_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for record in (b'CLFM', b'IDLE', b'NPC_'):
                make_plugin(root / 'patch.esp', masters=('Skyrim.esm',), records=(record,))
                assessment = assess_load_order(root, ['patch.esp']).assessments[0]
                self.assertTrue(assessment.esl_ready)
                self.assertEqual(assessment.esl_status, 'flag_directly')
                self.assertFalse(assessment.merge_ready)
            make_plugin(root / 'patch.esp', records=(b'ARMO',))
            assessment = assess_load_order(root, ['patch.esp']).assessments[0]
            self.assertFalse(assessment.esl_ready)
            self.assertEqual(assessment.esl_status, 'needs_compaction_review')

    def test_reads_flags_masters_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "patch.esp"
            make_plugin(path, TES4_LIGHT, ("Skyrim.esm",), (b"ARMO", b"COBJ"))
            info = parse_plugin(path)
            self.assertTrue(info.is_light)
            self.assertEqual(info.masters, ["Skyrim.esm"])
            self.assertEqual(info.record_count, 2)
            self.assertEqual(info.records["ARMO"], 1)

    def test_full_slot_count_includes_builtins_missing_from_plugins_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in BUILTIN_FULL_PLUGINS:
                (root / name).touch()
            make_plugin(root / "patch.esp", masters=("Skyrim.esm",))
            report = assess_load_order(root, ["patch.esp"])
            self.assertEqual(report.full_count, 6)
            self.assertEqual(report.remaining_full_slots, 248)


if __name__ == "__main__":
    unittest.main()
