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
    """Extract one member at a time under rules that leave nothing to re-point.

    Checking resolved paths is not enough on its own: an archive can re-point a link
    between one member's check and a later write. So the rules make links inert. A
    member's path is relative with no `..`; nothing is written through an existing link
    or over anything already extracted; a symlink points only downward (relative, no
    `..`); no hard links or special files; set-id bits are dropped. The pinned runtime
    (only same-folder symlinks) fits, and any violation stops the extraction."""
    root = os.path.realpath(target)
    def plain(rel):
        return rel and not os.path.isabs(rel) and '..' not in rel.split('/')
    for m in tf.getmembers():
        if not plain(m.name):
            raise SystemExit('Runtime archive entry escapes the target: %s; nothing trusted.' % m.name)
        dest = os.path.join(root, os.path.normpath(m.name))
        parent = os.path.dirname(dest)
        while parent != root:
            if os.path.islink(parent):
                raise SystemExit('Runtime archive writes through a link: %s; nothing trusted.' % m.name)
            parent = os.path.dirname(parent)
        if os.path.lexists(dest) and not (m.isdir() and os.path.isdir(dest) and not os.path.islink(dest)):
            raise SystemExit('Runtime archive replaces an entry: %s; nothing trusted.' % m.name)
        if m.issym():
            if not plain(m.linkname):
                raise SystemExit('Runtime archive link leaves its folder: %s; nothing trusted.' % m.name)
        elif not (m.isfile() or m.isdir()):
            raise SystemExit('Runtime archive holds a hard link or special file: %s; nothing trusted.' % m.name)
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
