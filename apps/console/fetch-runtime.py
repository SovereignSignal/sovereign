#!/usr/bin/env python3
"""Fetch the pinned Apple Silicon runtime into build/runtime, for building the app from source."""
import hashlib
import json
import os
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
def fenced(members):
    """Only regular files, directories and links that stay inside the target; no
    absolute or parent paths, devices or set-id bits. Raises on the first violation."""
    def inside(rel):
        rel = os.path.normpath(rel)
        return not os.path.isabs(rel) and rel != '..' and not rel.startswith('..' + os.sep)
    for m in members:
        if not inside(m.name):
            raise SystemExit('Runtime archive entry escapes the target: %s; nothing trusted.' % m.name)
        if m.issym():
            if os.path.isabs(m.linkname) or not inside(os.path.join(os.path.dirname(m.name), m.linkname)):
                raise SystemExit('Runtime archive link escapes the target: %s; nothing trusted.' % m.name)
        elif m.islnk():
            if not inside(m.linkname):
                raise SystemExit('Runtime archive hard link escapes the target: %s; nothing trusted.' % m.name)
        elif not (m.isfile() or m.isdir()):
            raise SystemExit('Runtime archive holds a special file: %s; nothing trusted.' % m.name)
        m.mode &= 0o755
        yield m


target = here / 'build/runtime'
if target.exists():
    raise SystemExit('Runtime directory exists; reuse it or choose a clean build directory.')
with tarfile.open(archive) as tf:
    # Python 3.12's data filter fences paths and symlink targets inside the target.
    # A Mac's own developer tools ship Python 3.9, which has no filter, so the same
    # fence is applied here: the archive's hash is already pinned, and this guards
    # extraction itself rather than trusting the archive's layout.
    if hasattr(tarfile, 'data_filter'):
        tf.extractall(target, filter='data')
    else:
        tf.extractall(target, members=fenced(tf.getmembers()))
print('Verified runtime:', target / 'python')
