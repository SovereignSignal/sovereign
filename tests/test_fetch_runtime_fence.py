"""apps/console/fetch-runtime.py: on a Python without tarfile's data filter (a Mac's own
3.9), extraction is fenced by hand, and an archive that tries to leave the target fails."""
import ast
import os
from pathlib import Path
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_fenced():
    tree = ast.parse((ROOT / 'apps/console/fetch-runtime.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fenced')
    ns = {'os': os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'fetch-runtime.py', 'exec'), ns)
    return ns['fenced']


def member(name, kind=tarfile.REGTYPE, linkname='', mode=0o644):
    m = tarfile.TarInfo(name)
    m.type, m.linkname, m.mode = kind, linkname, mode
    return m


class Fence(unittest.TestCase):
    def setUp(self):
        self.fenced = load_fenced()

    def test_ordinary_runtime_layout_passes_and_loses_set_id_bits(self):
        ms = [member('python', tarfile.DIRTYPE, mode=0o755), member('python/bin/python3.12', mode=0o4755),
              member('python/bin/python3', tarfile.SYMTYPE, 'python3.12'),
              member('python/lib/libpython.dylib', tarfile.LNKTYPE, 'python/lib/real.dylib')]
        out = list(self.fenced(ms))
        self.assertEqual(len(out), 4)
        self.assertEqual(out[1].mode, 0o755)

    def test_every_escape_is_refused(self):
        for bad in (member('../evil'), member('/etc/evil'), member('python/../../evil'),
                    member('python/bin/x', tarfile.SYMTYPE, '../../../etc/passwd'),
                    member('python/bin/y', tarfile.SYMTYPE, '/etc/passwd'),
                    member('python/z', tarfile.LNKTYPE, '../outside'),
                    member('python/dev', tarfile.CHRTYPE)):
            with self.subTest(name=bad.name, kind=bad.type):
                with self.assertRaises(SystemExit):
                    list(self.fenced([bad]))


if __name__ == '__main__':
    unittest.main()
