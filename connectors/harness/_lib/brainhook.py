"""Shared read-wire logic for every harness connector.

One implementation, many adapters. A harness hook (Claude Code, Cursor, Codex,
whatever comes next) is a few lines: read its own stdin shape, call build_pack()
with the working directory, wrap the result in the harness's output shape.

Rules every adapter inherits:
  - The pack is injected as context and never written anywhere else. A stored
    copy would come back through the loading dock as if it were new material.
  - Never fail the session. Callers wrap main() in try/except and exit 0.
  - One receipt line per session start in the lane, so reads can be counted.

Config, all instance-level:
  ~/.brain-root   vault path              (or $BRAIN_ROOT)
  ~/.brain-core   csv of always-on slugs  (or $BRAIN_CORE)
  ~/.brain-host   short host name         (or $BRAIN_HOST)
  $BRAIN_STAGE    staging root on TCC-protected Macs (default ~/.vault-staging if present)
  $BRAIN_HOOK_MAX_CARDS   topic cards in the pack, core rides on top (default 6)
  $BRAIN_HOOK_MAX_CHARS   cap on injected characters (default 40000)
"""
import os, sys, re, subprocess, datetime, shutil, socket

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def pointer(path):
    try:
        return open(os.path.expanduser(path), encoding="utf-8").read().strip() or None
    except OSError:
        return None


def vault_root():
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    return os.path.realpath(os.path.expanduser(root)) if root else None


def host_name():
    return (os.environ.get("BRAIN_HOST") or pointer("~/.brain-host")
            or socket.gethostname().split(".")[0].lower())


def core_slugs():
    return os.environ.get("BRAIN_CORE") or pointer("~/.brain-core") or ""


def find_brain_load():
    for cand in (os.path.join(TEMPLATE_ROOT, "bin", "brain-load"),
                 os.path.expanduser("~/brain-bin/brain-load"),
                 shutil.which("brain-load")):
        if cand and os.path.exists(cand):
            return cand
    return None


def lane_dir(root, lane):
    """Where this harness's receipts live. On a producer box with a git lane
    (~/.brain-lane), inside that lane under the harness prefix, so the mirror commits
    them with everything else. Otherwise the per-tool lane under raw/tools/ (via the
    staging hop on TCC-protected Macs)."""
    git_lane = os.environ.get("BRAIN_LANE") or pointer("~/.brain-lane")
    if git_lane and os.path.isdir(os.path.join(root, "raw", "workspaces", git_lane)):
        host = host_name()
        prefix = lane[:-(len(host) + 1)] if lane.endswith("-" + host) else lane
        return os.path.join(root, "raw", "workspaces", git_lane, prefix)
    stage = os.environ.get("BRAIN_STAGE")
    if stage:
        return os.path.join(stage, "raw", "tools", lane)
    vs = os.path.expanduser("~/.vault-staging")
    if os.path.isdir(vs):
        return os.path.join(vs, "raw", "tools", lane)
    return os.path.join(root, "raw", "tools", lane)


def identity_for(root, topic, scope):
    """The `identity:` label on the workstream front door, if any. No label means the default."""
    if not topic or scope != "workstream":
        return None
    p = os.path.join(root, "workstreams", topic, "overview.md")
    try:
        head = open(p, encoding="utf-8").read(2000)
    except OSError:
        return None
    if not head.startswith("---\n"):
        return None
    body = head[4:].split("\n---", 1)[0]          # the frontmatter block only
    m = re.search(r"(?m)^identity:\s*([A-Za-z0-9_-]+)\s*$", body)
    return m.group(1) if m else None


def topic_for(cwd, root):
    """workstreams/<name> or repos/<name> under the vault -> (name, scope); else (None, 'core')."""
    cwd = os.path.realpath(cwd)
    for folder in ("workstreams", "repos"):
        base = os.path.join(root, folder) + os.sep
        if cwd.startswith(base):
            return cwd[len(base):].split(os.sep)[0], folder[:-1]
    return None, "core"


def build_pack(cwd, harness):
    """Return dict(label, scope, cards, context) or None when there is nothing to load."""
    root = vault_root()
    if not root:
        return None
    core = core_slugs()
    topic, scope = topic_for(cwd, root)
    bl = find_brain_load()
    if not bl:
        sys.stderr.write("sovereign hook: brain-load not found\n")
        return None
    first_core = next((s.strip() for s in core.split(",") if s.strip()), None)
    entry = topic or first_core
    if not entry:
        return None
    args = [sys.executable, bl, entry, "--root", root,
            "--max", os.environ.get("BRAIN_HOOK_MAX_CARDS", "6")]
    if core:
        args += ["--core", core]
    if not topic:
        args += ["--depth", "0"]
    res = subprocess.run(args, capture_output=True, text=True, timeout=25)
    pack = res.stdout.strip()
    if not pack:
        return None
    m = re.search(r"_(\d+) cards from the knowledge layer", pack)
    cards = m.group(1) if m else ("core" if not topic else "0")
    limit = int(os.environ.get("BRAIN_HOOK_MAX_CHARS", "40000"))
    if len(pack) > limit:
        pack = pack[:limit] + "\n\n[pack truncated at %d chars; run `sov load %s` for the rest]" % (limit, entry)
    label = topic or "core"
    ident = identity_for(root, topic, scope)
    ident_line = ("Identity for this workstream: %s (the identities card in this pack says which name applies where)."
                  % ident) if ident else "Identity for this context: the default in the identities card, unless the workstream front door says otherwise."
    header = ("[Sovereign] Brain context for '%s' loaded from the owner's vault (%s). %s "
              "Treat the pack as current truth about the owner and his contexts and prefer it over guesses; "
              "where a tool's own memory disagrees, the pack wins and the disagreement is worth telling the owner. "
              "Do not copy it into memory files: it reloads every session. For more: `sov load <topic>`."
              % (label, root, ident_line))
    return {"label": label, "scope": scope, "cards": cards, "root": root, "identity": ident,
            "context": header + "\n\n" + pack, "harness": harness}


def receipt(root, lane, label, scope, cards, session_id=None, source=None):
    """Append one line to <lane>/brain-load-usage.md. Best effort; never raises to the caller."""
    try:
        d = lane_dir(root, lane)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "brain-load-usage.md")
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write("---\ntype: capture\nsource: %s\ncreated: %s\n"
                        "title: brain-load usage receipts\n---\n\n"
                        "One line per session start: time, topic, scope, cards loaded.\n\n"
                        % (lane, datetime.date.today().isoformat()))
        with open(p, "a", encoding="utf-8") as f:
            f.write("- %s %s scope=%s cards=%s source=%s session=%s\n" % (
                datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                label, scope, cards, source or "?", (session_id or "")[:8]))
    except Exception as e:
        sys.stderr.write("sovereign hook: receipt skipped: %s\n" % e)
