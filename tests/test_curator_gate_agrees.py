"""The curator's two walks must ask the same question about a file.

curator-run walks the vault twice: once in candidates() to pick what to judge, and
once to count `universe` for the coverage figure the app shows as archive
completeness. When the judge learned to read documents on 2026-09-20, the judging
walk moved to _judgeable() and the counting walk kept `endswith((".md", ".txt"))`.

Nothing broke loudly. The 55 documents on the hub were judgeable and simply absent
from `processable`, so the completeness percentage was computed against a universe
that excluded them - a number that looked fine and measured the wrong set. The
same shape as a preflight watching bytes while content was cut, and a guard
searching for the only name it could not be holding.
"""
import ast
import re
import unittest
from pathlib import Path

CURATOR = Path(__file__).resolve().parents[1] / "bin" / "curator-run"


class BothWalksAskTheSameQuestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = CURATOR.read_text(encoding="utf-8")

    def test_no_walk_filters_on_the_old_extension_pair(self):
        """PLAIN_EXT may name the pair; a walk may not test against it inline."""
        offenders = []
        for n, line in enumerate(self.source.splitlines(), 1):
            if "PLAIN_EXT" in line or line.lstrip().startswith("#"):
                continue
            if re.search(r'endswith\(\(\s*"\.md"\s*,\s*"\.txt"\s*\)\)', line):
                offenders.append("%s:%d: %s" % (CURATOR.name, n, line.strip()[:100]))
        self.assertEqual(offenders, [],
                         "a walk still asks the pre-2026-09-20 question. The judging walk "
                         "and the counting walk must agree, or the completeness figure "
                         "measures a different set than the judge reads.")

    def test_every_directory_walk_gates_on_judgeable(self):
        """Each `for f in fn:` filter routes through the one predicate."""
        tree = ast.parse(self.source)
        walks = [node for node in ast.walk(tree)
                 if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                 and node.target.id == "f" and isinstance(node.iter, ast.Name)
                 and node.iter.id == "fn"]
        self.assertGreaterEqual(len(walks), 2, "expected the judging walk and the counting walk")
        for walk in walks:
            with self.subTest(line=walk.lineno):
                names = {n.func.id for n in ast.walk(walk)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                self.assertIn("_judgeable", names,
                              "the walk at line %d does not use _judgeable" % walk.lineno)

    def test_the_predicate_names_documents_and_not_binaries(self):
        """Read structurally: curator-run exits at --self-test before _judgeable is
        defined, so it cannot be imported to be called. What matters here anyway is
        that one predicate exists and both walks route through it; the predicate's own
        behaviour is exercised by the shipped self-test and by the live pipeline."""
        tree = ast.parse(self.source)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_judgeable"), None)
        self.assertIsNotNone(fn, "_judgeable must exist; both walks depend on it")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("PLAIN_EXT", names, "it must still accept plain text")
        self.assertIn("_convertible", names, "and defer to the converters for documents")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
