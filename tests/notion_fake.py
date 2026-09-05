"""An in-memory Notion for the mirror tests. Same method names as notion_mirror.api.NotionClient."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.api import NotionError  # noqa: E402
from notion_mirror.config import norm_id  # noqa: E402

EDIT = "2026-09-01T00:00:00.000Z"


def hid(n):
    return "%032x" % n


def dashed(id32):
    return "-".join([id32[:8], id32[8:12], id32[12:16], id32[16:20], id32[20:]])


def rt(text):
    return {"type": "text", "plain_text": text, "text": {"content": text, "link": None},
            "annotations": {"bold": False, "italic": False, "strikethrough": False, "underline": False, "code": False}, "href": None}


def para(n, text):
    return {"object": "block", "id": dashed(hid(n)), "type": "paragraph", "has_children": False, "paragraph": {"rich_text": [rt(text)]}}


def image(n, url):
    return {"object": "block", "id": dashed(hid(n)), "type": "image", "has_children": False,
            "image": {"type": "file", "file": {"url": url}, "caption": []}}


def toggle(n, text):
    """A block with children of its own: the fetcher recurses into it."""
    return {"object": "block", "id": dashed(hid(n)), "type": "toggle", "has_children": True, "toggle": {"rich_text": [rt(text)]}}


def child_page_block(n):
    return {"object": "block", "id": dashed(hid(n)), "type": "child_page", "has_children": True, "child_page": {"title": ""}}


class FakeClient:
    def __init__(self):
        self.pages = {}
        self.data_sources = {}
        self.databases = {}
        self.blocks = {}
        self.block_objects = {}
        self.files = {}
        self.me = {"object": "user", "type": "bot", "name": "TestBot", "id": "bot", "bot": {"workspace_name": "Test WS"}}
        self.requests = 0
        self.queries = 0
        self.fail_children_for = set()
        self.fail_message = None

    # builders --------------------------------------------------------------
    @staticmethod
    def workspace():
        return {"type": "workspace", "workspace": True}

    @staticmethod
    def under(n):
        return {"type": "page_id", "page_id": dashed(hid(n))}

    def add_page(self, n, title, parent, edited=EDIT, props=None, body=()):
        obj = {"object": "page", "id": dashed(hid(n)), "last_edited_time": edited, "created_time": "2026-01-01T00:00:00.000Z",
               "in_trash": False, "parent": parent,
               "properties": props or {"title": {"type": "title", "title": [rt(title)]}}}
        self.pages[hid(n)] = obj
        self.blocks[hid(n)] = list(body)
        return obj

    def add_database(self, n, ds_n, title, database_parent, schema, edited=EDIT):
        ds = {"object": "data_source", "id": dashed(hid(ds_n)), "last_edited_time": edited, "in_trash": False, "is_inline": False,
              "parent": {"type": "database_id", "database_id": dashed(hid(n))}, "database_parent": database_parent,
              "title": [rt(title)], "properties": schema}
        self.data_sources[hid(ds_n)] = ds
        self.databases[hid(n)] = {"object": "database", "id": dashed(hid(n)), "data_sources": [{"id": dashed(hid(ds_n))}],
                                  "parent": database_parent, "title": [rt(title)]}
        return ds

    def add_row(self, n, db_n, ds_n, title, props, edited=EDIT, body=()):
        p = {"Name": {"type": "title", "title": [rt(title)]}}
        p.update(props)
        return self.add_page(n, title, {"type": "data_source_id", "data_source_id": dashed(hid(ds_n)), "database_id": dashed(hid(db_n))},
                             edited, props=p, body=body)

    def retitle(self, n, title, edited):
        obj = self.pages[hid(n)]
        for prop in obj["properties"].values():
            if prop["type"] == "title":
                prop["title"] = [rt(title)]
        obj["last_edited_time"] = edited

    # the client interface ---------------------------------------------------
    def request(self, method, path, body=None, params=None):
        self.requests += 1
        if path == "/users/me":
            return self.me
        raise NotionError("unexpected %s %s" % (method, path))

    def search(self, object_type=None):
        self.requests += 1
        objs = [o for o in self.pages.values() if not o.get("in_trash")] + [d for d in self.data_sources.values() if not d.get("in_trash")]
        if object_type == "page":
            objs = [o for o in objs if o["object"] == "page"]
        if object_type == "data_source":
            objs = [o for o in objs if o["object"] == "data_source"]
        return iter(sorted(objs, key=lambda o: o["last_edited_time"], reverse=True))

    def _get(self, table, key, what):
        self.requests += 1
        try:
            return table[norm_id(key)]
        except KeyError:
            raise NotionError("GET %s %s: HTTP 404: object_not_found" % (what, key))

    def page(self, i):
        return self._get(self.pages, i, "page")

    def block(self, i):
        return self._get(self.block_objects, i, "block")

    def data_source(self, i):
        return self._get(self.data_sources, i, "data_source")

    def database(self, i):
        return self._get(self.databases, i, "database")

    def query_rows(self, ds_id):
        self.requests += 1
        self.queries += 1
        return iter([p for p in self.pages.values()
                     if norm_id(p["parent"].get("data_source_id", "")) == norm_id(ds_id) and not p.get("in_trash")])

    def children(self, block_id):
        self.requests += 1
        if norm_id(block_id) in self.fail_children_for:
            raise NotionError(self.fail_message or ("GET /blocks/%s/children: HTTP 500: boom" % block_id))
        return [dict(b) for b in self.blocks.get(norm_id(block_id), [])]

    def download(self, url):
        self.requests += 1
        if url not in self.files:
            raise NotionError("download %s: expired" % url)
        return self.files[url]
