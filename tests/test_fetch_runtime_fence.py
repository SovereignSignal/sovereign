"""apps/console/fetch-runtime.py: on a Python without tarfile's data filter (a Mac's own
3.9), extraction is fenced against the real filesystem, so an archive that tries to leave
the target fails, including through a chain of links that each read as inside."""
import ast
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_extract_fenced():
    tree = ast.parse((ROOT / 'apps/console/fetch-runtime.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_fenced')
    ns = {'os': os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'fetch-runtime.py', 'exec'), ns)
    return ns['extract_fenced']


def archive(entries):
    """entries: (name, kind, linkname_or_bytes, mode)"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tf:
        for name, kind, extra, mode in entries:
            m = tarfile.TarInfo(name); m.type = kind; m.mode = mode
            if kind == tarfile.REGTYPE:
                m.size = len(extra); tf.addfile(m, io.BytesIO(extra))
            else:
                m.linkname = extra or ''; tf.addfile(m)
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode='r')


class Fence(unittest.TestCase):
    def setUp(self):
        self.extract = load_extract_fenced()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.target = self.base / 'runtime'; self.target.mkdir()

    def test_ordinary_runtime_layout_extracts_without_set_id_bits(self):
        tf = archive([('python', tarfile.DIRTYPE, None, 0o755), ('python/bin', tarfile.DIRTYPE, None, 0o755),
                      ('python/bin/python3.12', tarfile.REGTYPE, b'#!', 0o4755),
                      ('python/bin/python3', tarfile.SYMTYPE, 'python3.12', 0o777),
                      ('python/bin/hard', tarfile.LNKTYPE, 'python/bin/python3.12', 0o755)])
        self.extract(tf, self.target)
        exe = self.target / 'python/bin/python3.12'
        self.assertEqual(exe.stat().st_mode & 0o7777, 0o755)
        self.assertEqual(os.readlink(self.target / 'python/bin/python3'), 'python3.12')

    def test_every_escape_is_refused_and_nothing_lands_outside(self):
        cases = {
            'parent path': [('../evil', tarfile.REGTYPE, b'x', 0o644)],
            'absolute path': [('/tmp/sovereign-fence-evil', tarfile.REGTYPE, b'x', 0o644)],
            'escaping symlink': [('python/x', tarfile.SYMTYPE, '../../evil', 0o777)],
            'absolute symlink': [('python/y', tarfile.SYMTYPE, '/etc/passwd', 0o777)],
            'escaping hard link': [('python/z', tarfile.LNKTYPE, '../outside', 0o644)],
            'special file': [('python/dev', tarfile.CHRTYPE, None, 0o644)],
            # each link reads as inside; together they land outside
            'chained links': [('a', tarfile.SYMTYPE, '.', 0o777), ('a/b', tarfile.SYMTYPE, '../evil', 0o777),
                              ('a/b/payload', tarfile.REGTYPE, b'x', 0o644)],
            'file through a directory link': [('d', tarfile.SYMTYPE, '..', 0o777),
                                              ('d/evil', tarfile.REGTYPE, b'x', 0o644)],
        }
        for label, entries in cases.items():
            with self.subTest(label):
                target = self.base / label.replace(' ', '-'); target.mkdir()
                before = sorted(os.listdir(self.base))
                with self.assertRaises(SystemExit):
                    self.extract(archive(entries), target)
                self.assertEqual(sorted(os.listdir(self.base)), before)
                self.assertFalse(Path('/tmp/sovereign-fence-evil').exists())


if __name__ == '__main__':
    unittest.main()
