"""Read-only MCP server over stdio: curated cards from knowledge/, and no write path at all.

It serves the slice `sov load` serves (an entry card, its linked neighbours, the always-on core),
but reads through archive_evidence.cards: no symlink is followed, an ambiguous slug fails closed,
and every card is served with its path and content hash so a client can cite exactly what it read.
The read gate is checked on every call, so moving a client to contribute-only, or retiring the
`mcp` harness, takes effect without restarting the server.
"""
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import brain_discovery
from archive_evidence.cards import BoundCard, CardError, bind_topic, card_index, load_aliases
from brain_redact import redact_text
from sovereign_config import pointer

HARNESS = "mcp"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LINK = re.compile(r"\[\[([a-z0-9-]+)\]\]")
TITLE = re.compile(r"(?m)^title:\s*(.+?)\s*$")
MAX_CHARS = 40000  # the session hook's default pack budget
MAX_LIST = 500
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {"name": "load_context",
     "description": "Load the archive's context pack for a topic: the topic's card, the cards it links to, "
                    "and the always-on core. Call this before working on something the archive may know about.",
     "inputSchema": {"type": "object", "properties": {
         "topic": {"type": "string", "description": "A card slug or alias, e.g. garden-planner"},
         "depth": {"type": "integer", "minimum": 0, "maximum": 3, "description": "Link hops to follow (default 2)"}},
         "required": ["topic"]}},
    {"name": "read_card",
     "description": "Read one trusted card by slug, with its path and content hash.",
     "inputSchema": {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}},
    {"name": "search_cards",
     "description": "Find trusted cards whose slug, title or text match a query. Returns slugs to pass to read_card.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]}},
    {"name": "list_cards",
     "description": "List every trusted card in the archive by kind, slug and title.",
     "inputSchema": {"type": "object", "properties": {}}},
]
for _tool in TOOLS:
    _tool["annotations"] = READ_ONLY


class Refused(Exception):
    """A request the server answers with an error result instead of content."""


def read_allowed() -> bool:
    try:
        if HARNESS in brain_discovery.manifest().get("retired_harnesses", {}):
            return False
    except (OSError, ValueError, TypeError):
        return False
    return brain_discovery.read_enabled()


def archive_root() -> Optional[Path]:
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    return Path(os.path.expanduser(root)) if root else None


def core_slugs() -> List[str]:
    return [s.strip() for s in (pointer("~/.brain-core") or "").split(",") if s.strip()]


def served(card: BoundCard) -> str:
    """What a client sees for one card: provenance first, then the card with any secret shape redacted.

    Cards are redacted when they are written; doing it again here keeps a card someone hand-edited
    with a pasted key from leaving through a reader that may belong to a third-party tool.
    """
    text, _ = redact_text(card.text)
    return f"<!-- {card.relative_path} sha256:{card.content_sha256} -->\n{text.rstrip()}"


class Archive:
    def __init__(self, root: Path):
        self.root = root
        self.aliases = load_aliases(root)

    def bind(self, slug: str) -> BoundCard:
        return bind_topic(self.root, slug, self.aliases)

    def pack(self, topic: str, depth: int = 2, max_cards: int = 25, max_chars: int = MAX_CHARS) -> str:
        order, cards = [], {}
        queue, missing = deque([(topic, 0)]), None
        while queue and len(order) < max_cards:
            slug, hops = queue.popleft()
            if slug in cards:
                continue
            try:
                card = self.bind(slug)
            except CardError as exc:
                if hops == 0:
                    missing = str(exc)
                continue
            if card.slug in cards:  # an alias resolved to a card already loaded
                continue
            cards[card.slug] = card
            order.append(card.slug)
            if hops < depth:
                queue.extend((link, hops + 1) for link in LINK.findall(card.text) if link not in cards)
        for slug in core_slugs():
            if slug not in cards:
                try:
                    cards[slug] = self.bind(slug)
                    order.append(slug)
                except CardError:
                    pass
        if missing:
            head = (f"# Archive context pack — {topic}\n_No card for '{topic}' ({missing}). "
                    f"This is the always-on core only; search_cards can find the right slug._")
        else:
            head = (f"# Archive context pack — {topic}\n_{len(order)} cards from the trusted layer, "
                    f"each with its source path and content hash._")
        body = "\n\n----\n\n".join(served(cards[s]) for s in order)
        text = head + "\n\n" + body if body else head
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[pack truncated at {max_chars} chars; read_card loads any card in full]"
        return text

    def cards(self) -> List[Tuple[str, str, BoundCard]]:
        """(kind, title, card) for every servable card. An ambiguous or unsafe slug is never served, so never listed."""
        rows = []
        for slug, paths in sorted(card_index(self.root).items()):
            if len(paths) != 1:
                continue
            try:
                card = self.bind(slug)
            except CardError:
                continue
            title = TITLE.search(card.text)
            rows.append((paths[0].parent.name, title.group(1).strip("\"'") if title else "", card))
        return rows

    def search(self, query: str, limit: int = 10) -> List[Tuple[int, str, str]]:
        terms = [t for t in re.split(r"\W+", query.lower()) if t]
        if not terms:
            raise Refused("The query has no words to search for.")
        hits = []
        for kind, title, card in self.cards():
            slug, text = card.slug, card.text.lower()
            name = f"{slug} {title}".lower()
            score = sum(3 * name.count(t) + min(text.count(t), 5) for t in terms)
            if score and all(t in text or t in name for t in terms):
                hits.append((score, slug, f"{kind}: {title or slug}"))
        return sorted(hits, key=lambda h: (-h[0], h[1]))[:limit]


def call(name: str, args: dict) -> str:
    if not read_allowed():
        raise Refused("Context reading is disabled for this client mode, for the mcp harness, "
                      "or by an invalid role configuration.")
    root = archive_root()
    if not root:
        raise Refused("No archive is configured on this Mac. Create one in the Sovereign app or run sov init.")
    try:
        archive = Archive(root)
        if name == "load_context":
            topic = args.get("topic")
            depth = args.get("depth", 2)
            if not isinstance(topic, str) or not topic.strip():
                raise Refused("load_context needs a topic.")
            if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 3:
                raise Refused("depth must be an integer from 0 to 3.")
            return archive.pack(topic.strip(), depth)
        if name == "read_card":
            slug = args.get("slug")
            if not isinstance(slug, str):
                raise Refused("read_card needs a slug.")
            return served(archive.bind(slug.strip()))
        if name == "search_cards":
            query, limit = args.get("query"), args.get("limit", 10)
            if not isinstance(query, str):
                raise Refused("search_cards needs a query.")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise Refused("limit must be an integer from 1 to 50.")
            hits = archive.search(query, limit)
            return "\n".join(f"- {slug} ({label})" for _, slug, label in hits) or "No trusted card matches."
        if name == "list_cards":
            rows = archive.cards()
            lines = [f"- {kind}/{card.slug}" + (f": {title}" if title else "") for kind, title, card in rows[:MAX_LIST]]
            if len(rows) > MAX_LIST:
                lines.append(f"[{len(rows) - MAX_LIST} more; search_cards narrows the list]")
            return "\n".join(lines) or "The trusted layer has no cards yet."
    except CardError as exc:
        raise Refused(f"The archive refused the read: {exc}.") from exc
    raise Refused(f"Unknown tool: {name}")


def handle(message) -> Optional[dict]:
    """One JSON-RPC message in, at most one response out. Notifications get no response."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if "id" not in message:
        return None
    ident, method, params = message["id"], message["method"], message.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        return ok({"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "sovereign", "version": "0.8.0"},
                   "instructions": "Sovereign's trusted archive, read-only. Call load_context with the topic "
                                   "you are working on before you start; cite cards by their path."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Invalid params"}}
        args = params.get("arguments") or {}
        try:
            text, failed = call(params["name"], args if isinstance(args, dict) else {}), False
        except Refused as exc:
            text, failed = str(exc), True
        return ok({"content": [{"type": "text", "text": text}], "isError": failed})
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def main(argv: List[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: sov mcp\n\nServe the archive's trusted cards to an MCP client over stdio, read-only.\n"
              "Register it with a client, e.g.: claude mcp add sovereign -- sov mcp")
        return 0
    if argv:
        print(f"sov mcp: unexpected argument {argv[0]!r}", file=sys.stderr)
        return 64
    return serve()
