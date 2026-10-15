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


def extract_fenced(tf, target):
    """Extract one member at a time, each checked against the real filesystem first.

    Spelling alone cannot fence a tar: a link `a -> .` followed by `a/b -> ../x` reads as
    inside and lands outside. So every destination, and every link's target, is resolved
    with the links already extracted, and must stay under the target. Only regular files,
    directories and links; no special files; set-id bits dropped. Stops at the first
    violation, leaving whatever was extracted so far inside the target."""
    root = os.path.realpath(target)
    def inside(path):
        return os.path.commonpath([os.path.realpath(path), root]) == root
    for m in tf.getmembers():
        dest = os.path.join(root, m.name)
        if os.path.isabs(m.name) or not inside(dest):
            raise SystemExit('Runtime archive entry escapes the target: %s; nothing trusted.' % m.name)
        if m.issym():
            if os.path.isabs(m.linkname) or not inside(os.path.join(os.path.dirname(dest), m.linkname)):
                raise SystemExit('Runtime archive link escapes the target: %s; nothing trusted.' % m.name)
        elif m.islnk():
            if os.path.isabs(m.linkname) or not inside(os.path.join(root, m.linkname)):
                raise SystemExit('Runtime archive hard link escapes the target: %s; nothing trusted.' % m.name)
        elif not (m.isfile() or m.isdir()):
            raise SystemExit('Runtime archive holds a special file: %s; nothing trusted.' % m.name)
        m.mode &= 0o755
        tf.extract(m, root)


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
        target.mkdir(parents=True)
        extract_fenced(tf, target)
print('Verified runtime:', target / 'python')
