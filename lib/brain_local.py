"""Local archive operations used by the downloadable app. No network or job control."""
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from brain_redact import redact_text

FOLDERS = ('raw', 'workstreams', 'knowledge', 'archive', 'repos')
# Kept out of history: code working trees, cold storage, editor state and Finder litter.
GITIGNORE = '.DS_Store\n.obsidian/workspace*\narchive/\nrepos/\n'
# Used only when git has no identity it can use for this repository.
FALLBACK_IDENTITY = ('Sovereign', 'sovereign@localhost')
NO_GIT = 'git was not found; the archive has no history yet.'
NO_COMMIT = 'git could not make the first commit; the archive has no history yet.'


def archive_root(value):
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir() or any(not (root / d).is_dir() or (root / d).is_symlink() for d in FOLDERS):
        raise ValueError('Choose an archive with raw, workstreams, knowledge, archive, and repos folders.')
    return root


def create(value, template):
    root = Path(value).expanduser().absolute()
    if not root.name.strip() or any(c in root.name for c in '\n\r\x00'):
        raise ValueError('Choose a folder name on one line.')
    if not root.parent.is_dir():
        raise ValueError('Choose an existing parent folder.')
    # Exclusive mkdir is the no-overwrite boundary, including an empty directory.
    root.mkdir(mode=0o700)
    for folder in FOLDERS:
        (root / folder).mkdir()
    for folder in ('entities', 'concepts', 'syntheses'):
        (root / 'knowledge' / folder).mkdir()
    (root / 'raw/tools').mkdir()
    (root / 'raw/workspaces').mkdir()
    (root / '.obsidian/templates').mkdir(parents=True)
    shutil.copyfile(template / 'templates/note.md', root / '.obsidian/templates/note.md')
    law = (template / 'CLAUDE.md').read_text().replace('{{SOVEREIGN_NAME}}', root.name).replace('{{BRAIN_NAME}}', root.name)
    (root / 'CLAUDE.md').write_text(law)
    for keep in ('raw/tools', 'raw/workspaces', 'workstreams', 'knowledge/entities',
                 'knowledge/concepts', 'knowledge/syntheses', 'archive', 'repos'):
        (root / keep / '.gitkeep').touch()
    result = {'root': str(root.resolve()), 'name': root.name}
    result.update(init_repository(root, root.name))
    return result


def _find_git():
    """The git to run, or None. Mirrors bin/git-guard on a Mac.

    Without Apple's developer tools /usr/bin/git is a shim that opens an install dialog, so
    on a Mac PATH only says whether git is there, and the binary is chosen the way the guard
    chooses it. A git that cannot answer --version (an unaccepted Xcode licence) is none.
    """
    git = shutil.which('git')
    if git and sys.platform == 'darwin':
        try:
            tools = subprocess.run(['/usr/bin/xcode-select', '-p'], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            tools = False
        found = ['/usr/bin/git'] if tools else [g for g in ('/opt/homebrew/bin/git', '/usr/local/bin/git') if os.access(g, os.X_OK)]
        git = found[0] if found else None
    if not git:
        return None
    try:
        ok = subprocess.run([git, '--version'], capture_output=True, stdin=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return git if ok else None


def init_repository(root, name):
    """Write the ignore file and make the archive a git repository with one first commit.

    The one place both the app (create) and the CLI (bin/sov-init) start history, so the
    two cannot drift. Without git the archive still stands: the result says it has no
    history. The owner's global git config is never touched; a repository-local identity
    is set only when git has none it can use.
    """
    root = Path(root)
    (root / '.gitignore').write_text(GITIGNORE)
    git = _find_git()
    if not git:
        return {'git': False, 'git_message': NO_GIT}

    def run(*args):
        return subprocess.run([git, *args], cwd=root, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=20)

    fresh = not (root / '.git').exists()
    try:
        if run('init', '-q').returncode:
            raise subprocess.SubprocessError
        if run('var', 'GIT_AUTHOR_IDENT').returncode or run('var', 'GIT_COMMITTER_IDENT').returncode:
            run('config', 'user.name', FALLBACK_IDENTITY[0])
            run('config', 'user.email', FALLBACK_IDENTITY[1])
        if run('add', '-A').returncode or run('commit', '-q', '-m', 'new instance: %s (from Sovereign)' % name).returncode:
            raise subprocess.SubprocessError
    except (OSError, subprocess.SubprocessError):
        # A half-made repository would claim history it does not have.
        if fresh:
            shutil.rmtree(root / '.git', ignore_errors=True)
        return {'git': False, 'git_message': NO_COMMIT}
    return {'git': True}


def note_path(root, relative):
    candidate = root / relative
    # No hidden files, symlinks or paths outside the three active note zones.
    parts = Path(relative).parts
    if not parts or parts[0] not in ('raw', 'workstreams', 'knowledge') or any(p.startswith('.') for p in parts):
        raise ValueError('This file is outside the active archive.')
    for i in range(1, len(parts) + 1):
        if root.joinpath(*parts[:i]).is_symlink():
            raise ValueError('Linked files are not opened by the archive reader.')
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved.suffix.lower() != '.md' or not resolved.is_file():
        raise ValueError('Choose a Markdown note inside this archive.')
    if resolved.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Open notes larger than 2 MiB in your text editor.')
    return resolved


def document(path):
    raw = path.read_text(encoding='utf-8')
    body, title = raw, None
    fm = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', raw, re.S)
    if fm:
        body = raw[fm.end():].lstrip()
        value = re.search(r'(?m)^title:\s*([^\r\n]+)', fm.group(1))
        if value:
            title = value.group(1).strip()
            if title.startswith('"'):
                try: title = json.loads(title)
                except ValueError: pass
            elif title.startswith("'") and title.endswith("'"):
                title = title[1:-1].replace("''", "'")
    heading = re.search(r'(?m)^#\s+(.+)', body)
    title = title or (heading.group(1) if heading else re.sub(r'-[a-f0-9]{12}$', '', path.stem).replace('-', ' '))
    return {'title': str(title), 'body': raw, 'text': body}


def read(root, relative):
    return dict(document(note_path(root, relative)), path=relative)


def listing(root, query=''):
    records = []
    total = 0
    for zone in ('knowledge', 'workstreams', 'raw'):
        for path in sorted((root / zone).rglob('*.md')):
            rel = str(path.relative_to(root))
            try:
                p = note_path(root, rel)
                doc = document(p)
                title = doc['title']
                if query and query.casefold() not in (title + '\n' + doc['text']).casefold():
                    continue
                total += 1
                if len(records) < 500:
                    records.append({'path': rel, 'title': title, 'zone': zone})
            except (OSError, ValueError, UnicodeError):
                continue
    return {'root': str(root), 'name': root.name, 'notes': records, 'total': total,
            'limited': total > len(records), 'observed_at': datetime.now(timezone.utc).isoformat()}


def capture(root, title, body):
    title = title.strip()
    body = body.strip()
    if not title or len(title) > 160 or any(c in title for c in '\r\n\x00'):
        raise ValueError('Add a title of up to 160 characters on one line.')
    if not body or len(body.encode()) > 1024 * 1024:
        raise ValueError('Add a note smaller than 1 MiB.')
    clean_title, title_hits = redact_text(title)
    clean_body, body_hits = redact_text(body)
    slug = re.sub('[^a-z0-9]+', '-', clean_title.lower()).strip('-')[:72] or 'note'
    lane = root / 'raw/workspaces/owner'
    for part in (root / 'raw', root / 'raw/workspaces', lane):
        if part.is_symlink():
            raise ValueError('The capture destination contains a symbolic link.')
    lane.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = '%s-%s.md' % (slug, uuid.uuid4().hex[:12])
    p = lane / filename
    today = datetime.now().date().isoformat()
    content = '---\ntype: capture\nsource: owner\ncreated: %s\ntitle: %s\n---\n\n%s\n' % (today, json.dumps(clean_title, ensure_ascii=False), clean_body)
    # Exclusive create also protects an existing note if a filename collides.
    with p.open('x', encoding='utf-8') as f:
        f.write(content)
    return {'path': str(p.relative_to(root)), 'redactions': len(title_hits) + len(body_hits)}

def context_state(root):
    """Read existing hook receipts, never infer receipt of context by a model.

    The shared hook writes these before returning its payload. They prove only
    preparation. Installation/manual receipts stay labelled as tests.
    """
    receipts, skipped = [], 0
    # Only the existing producer layouts. Never crawl arbitrary owner documents.
    candidates = []
    for zone, max_depth in (('raw/tools', 1), ('raw/workspaces', 2)):
        base = root / zone
        if base.is_symlink():
            skipped += 1
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            parent = Path(directory)
            depth = len(parent.relative_to(base).parts)
            dirs[:] = [d for d in dirs if not d.startswith('.') and not (parent / d).is_symlink()] if depth < max_depth else []
            if depth > 0 and 'brain-load-usage.md' in files:
                candidates.append(parent / 'brain-load-usage.md')
    # slugs= (the cards the session got) is on receipts written since build 45; older lines lack it.
    pattern = re.compile(r'^- (\S+) (\S+) scope=(\S+) cards=(\S+) source=(\S+) session=(\S*?)(?: slugs=(\S+))?\s*$')
    now = datetime.now(timezone.utc)
    for candidate in sorted(set(candidates)):
        relative = str(candidate.relative_to(root))
        try:
            path = note_path(root, relative)
            latest = None
            for line in path.read_text(encoding='utf-8').splitlines():
                match = pattern.fullmatch(line)
                if not match:
                    continue
                stamp, topic, scope, cards, source, session, slugs = match.groups()
                try:
                    when = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                    if when.tzinfo is None or when > now:
                        continue
                except ValueError:
                    continue
                if latest is None or when > latest[0]:
                    latest = (when, {'path': relative, 'producer': str(Path(relative).parent.relative_to('raw')),
                        'topic': topic, 'scope': scope, 'cards': cards, 'slugs': slugs.split(',') if slugs else [], 'prepared_at': stamp,
                        'source': source, 'test': session.startswith(('manual', 'install-', 'pilot')),
                        'prepared': True, 'delivered': None, 'loaded': None})
            if latest:
                receipts.append(latest[1])
        except (OSError, ValueError, UnicodeError):
            skipped += 1
    receipts.sort(key=lambda r: datetime.fromisoformat(r['prepared_at'].replace('Z', '+00:00')), reverse=True)
    return {'root': str(root), 'receipts': receipts[:100], 'total': len(receipts),
            'limited': len(receipts) > 100, 'skipped': skipped, 'observed_at': now.isoformat()}
