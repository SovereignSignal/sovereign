"""Run the archive's own credential scanner over what the mirror wrote, so a secret that
slipped past the excludes is reported by the run itself, not discovered later by the
vault's autocommit.

Contract with the scanner (any executable): argv[1] is a file listing vault-relative
paths, one per line; the cwd is the vault root; exit 0 means clean, anything else means
hits; whatever it prints is kept in <state>/secret-scan.log. The flagged files are the
listed paths its output names, so the status line can point at the first one.
"""
import subprocess
from pathlib import Path
from typing import List

TIMEOUT_SECONDS = 1800


class ScanError(RuntimeError):
    """The scanner could not run at all. Distinct from hits: a run that cannot be
    scanned is not known to be clean."""


def run_scan(scanner: str, brain_root: Path, rel_paths: List[str], state_dir: Path) -> List[str]:
    if not rel_paths:
        return []
    listing = state_dir / "secret-scan.list"
    listing.write_text("\n".join(rel_paths) + "\n", encoding="utf-8")
    try:
        proc = subprocess.run([scanner, str(listing)], cwd=str(brain_root), capture_output=True,
                              text=True, errors="replace", timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanError("secret scan could not run (%s): %s" % (scanner, exc))
    (state_dir / "secret-scan.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode == 0:
        return []
    flagged = [p for p in rel_paths if p in proc.stdout]
    return flagged or ["(unnamed; see secret-scan.log)"]
