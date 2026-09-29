import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from sparky.builder import BuildError, build_esl_overlay, build_merge, flag_esl_now
from sparky.plugins import TES4_LIGHT, parse_plugin


def patch_plugin(path: Path, master="Skyrim.esm", value=b"A", form_id=0x00001234):
    (path.parent / master).touch(exist_ok=True)
    hedr = b"HEDR" + struct.pack("<HfII", 12, 1.7, 1, 0x800)
    mast = b"MAST" + struct.pack("<H", len(master) + 1) + master.encode() + b"\0"
    mast += b"DATA" + struct.pack("<H", 8) + b"\0" * 8
    payload = hedr + mast
    header = b"TES4" + struct.pack("<II", len(payload), 0) + b"\0" * 12 + payload
    record = b"GMST" + struct.pack("<III", len(value), 0, form_id) + b"\0" * 8 + value
    group = b"GRUP" + struct.pack("<I", 24 + len(record)) + b"GMST" + b"\0" * 12 + record
    path.write_bytes(header + group)


class BuilderTests(unittest.TestCase):
    def test_direct_flag_preserves_backup_and_hardlinked_provider(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'patch.esp'
            patch_plugin(source)
            original = source.read_bytes()
            provider = root / 'provider.esp'
            os.link(source, provider)
            backup = flag_esl_now(root, ['patch.esp'], 'patch.esp', root / 'backups')
            changed = source.read_bytes()
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(provider.read_bytes(), original)
            self.assertEqual(changed[:8] + changed[12:], original[:8] + original[12:])
            self.assertTrue(parse_plugin(source).is_light)
            with self.assertRaises(BuildError):
                flag_esl_now(root, ['patch.esp'], 'patch.esp', root / 'backups')

    def test_protected_skeleton_rejected_by_scan_and_both_builders(self):
        from sparky.plugins import assess_load_order
        for name in ('XPMSE.esp', 'xpmsse.ESP', 'XP32.esp', 'XPMSE - Patch.esp'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                patch_plugin(root / name)
                patch_plugin(root / 'ordinary.esp')
                names = [name, 'ordinary.esp']
                assessment = assess_load_order(root, names).assessments[0]
                self.assertFalse(assessment.merge_ready)
                self.assertFalse(assessment.merge_candidate)
                self.assertFalse(assessment.esl_review_candidate)
                self.assertFalse(assessment.esl_ready)
                self.assertIn('Protected', ';'.join(assessment.reasons))
                original = (root / name).read_bytes()
                with self.assertRaises(BuildError):
                    build_merge(root, names, names, 'merged.esp', root / 'out')
                with self.assertRaises(BuildError):
                    build_esl_overlay(root, names, name, root / 'out')
                with self.assertRaises(BuildError):
                    flag_esl_now(root, names, name, root / 'out')
                self.assertEqual((root / name).read_bytes(), original)
                self.assertFalse((root / 'out').exists())

    def test_merge_preserves_later_override_and_masters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch_plugin(root / "first.esp", value=b"A")
            patch_plugin(root / "second.esp", value=b"B")
            archive = build_merge(root, ["first.esp", "second.esp"], ["second.esp", "first.esp"], "merged.esp", root / "out")
            with zipfile.ZipFile(archive) as bundle:
                output = bundle.read("merged.esp")
            self.assertEqual(output[-1:], b"B")
            self.assertEqual(struct.unpack_from("<I", output, 34)[0], 1)
            self.assertEqual(len(parse_plugin_from_bytes(root, output).masters), 1)

    def test_esl_overlay_changes_only_header_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "patch.esp"
            patch_plugin(source)
            archive = build_esl_overlay(root, ["patch.esp"], "patch.esp", root / "out")
            with zipfile.ZipFile(archive) as bundle:
                changed = bundle.read("patch.esp")
            original = source.read_bytes()
            self.assertEqual(changed[:8] + changed[12:], original[:8] + original[12:])
            self.assertEqual(struct.unpack_from("<I", changed, 8)[0], TES4_LIGHT)

    def test_merge_rejects_different_master_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch_plugin(root / "first.esp", master="Skyrim.esm")
            patch_plugin(root / "second.esp", master="Update.esm")
            with self.assertRaises(BuildError):
                build_merge(root, ["first.esp", "second.esp"], ["first.esp", "second.esp"], "merged.esp", root / "out")


def parse_plugin_from_bytes(root: Path, data: bytes):
    path = root / "validated.esp"
    path.write_bytes(data)
    return parse_plugin(path)
