#!/usr/bin/env python3
"""Fetch the pinned Apple Silicon runtime into build/runtime. For maintainers only."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

here = Path(__file__).resolve().parent
lock = json.loads((here / 'runtime.lock.json').read_text())
archive = here / 'build/python-runtime.tar.gz'
archive.parent.mkdir(parents=True, exist_ok=True)
if not archive.exists():
    with urllib.request.urlopen(lock['url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != lock['sha256']:
        raise SystemExit('Runtime checksum mismatch; nothing extracted.')
    archive.write_bytes(data)
if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['sha256']:
    raise SystemExit('Cached runtime checksum mismatch; nothing extracted.')
target = here / 'build/runtime'
if target.exists():
    raise SystemExit('Runtime directory exists; reuse it or choose a clean build directory.')
with tarfile.open(archive) as tf:
    # Python 3.12 data filters also fence symlink targets. Older build hosts must
    # use an interpreter with extraction filters rather than weaken this boundary.
    if not hasattr(tarfile, 'data_filter'):
        raise SystemExit('Use Python 3.12 or newer to unpack the runtime safely.')
    tf.extractall(target, filter='data')
print('Verified runtime:', target / 'python')
