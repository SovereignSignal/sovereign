import tempfile
import unittest
from pathlib import Path

from archive_evidence.safeio import SafetyError, read_json_private, write_json_exclusive


class SafeIoTests(unittest.TestCase):
    def test_private_output_rejects_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            output = root / "receipt.json"
            output.write_text("existing")

            with self.assertRaisesRegex(SafetyError, "output_exists"):
                write_json_exclusive(output, {"ok": True}, root)

    def test_private_output_rejects_path_outside_project(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as other_tmp:
            project = Path(project_tmp)
            other = Path(other_tmp)
            project.chmod(0o700)
            other.chmod(0o700)

            with self.assertRaisesRegex(SafetyError, "output_outside_project"):
                write_json_exclusive(other / "receipt.json", {"ok": True}, project)

    def test_private_output_rejects_symlinked_parent_component(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            project = Path(project_tmp)
            outside = Path(outside_tmp)
            project.chmod(0o700)
            outside.chmod(0o700)
            (outside / "nested").mkdir(mode=0o700)
            (project / "linked").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(SafetyError, "unsafe_output_parent"):
                write_json_exclusive(project / "linked" / "nested" / "receipt.json", {"ok": True}, project)

    def test_private_json_reader_rejects_symlink_and_returns_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            project = Path(tmp)
            project.chmod(0o700)
            regular = project / "overlay.json"
            regular.write_text('{"ok":true}')
            regular.chmod(0o600)
            target = Path(other) / "outside.json"
            target.write_text('{"ok":false}')
            linked = project / "linked.json"
            linked.symlink_to(target)

            self.assertEqual(read_json_private(regular, project), {"ok": True})
            with self.assertRaisesRegex(SafetyError, "unsafe_private_input"):
                read_json_private(linked, project)


if __name__ == "__main__":
    unittest.main()
