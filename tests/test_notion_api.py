import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.api import NotionClient, NotionError  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "err", headers or {}, io.BytesIO(b'{"message":"rate limited"}'))


class FakeOpener:
    """Scripted responses: each entry is a dict (200 JSON) or an HTTPError."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def __call__(self, req, timeout=0):
        self.seen.append((req.get_method(), req.full_url, req.data, dict(req.header_items())))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return Resp(json.dumps(item).encode("utf-8"))


class Client(unittest.TestCase):
    def test_sends_auth_and_version_headers(self):
        opener = FakeOpener([{"object": "user", "name": "bot"}])
        c = NotionClient("tok", version="2026-03-11", opener=opener, sleep=lambda s: None)
        out = c.request("GET", "/users/me")
        self.assertEqual(out["name"], "bot")
        method, url, data, headers = opener.seen[0]
        self.assertEqual(url, "https://api.notion.com/v1/users/me")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["Notion-version"], "2026-03-11")
        self.assertEqual(c.requests, 1)

    def test_retries_on_429_honouring_retry_after(self):
        slept = []
        opener = FakeOpener([http_error(429, {"Retry-After": "3"}), {"ok": True}])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0)
        self.assertEqual(c.request("GET", "/pages/x"), {"ok": True})
        self.assertIn(3.0, slept)

    def test_gives_up_after_retries_with_notion_error(self):
        opener = FakeOpener([http_error(500)] * 3)
        c = NotionClient("tok", opener=opener, sleep=lambda s: None, retries=2, min_interval=0)
        with self.assertRaises(NotionError):
            c.request("GET", "/pages/x")

    def test_4xx_other_than_429_is_immediate(self):
        opener = FakeOpener([http_error(404)])
        c = NotionClient("tok", opener=opener, sleep=lambda s: None, min_interval=0)
        with self.assertRaises(NotionError) as ctx:
            c.request("GET", "/pages/x")
        self.assertIn("404", str(ctx.exception))
        self.assertEqual(len(opener.script), 0)

    def test_paginate_follows_cursor_in_body_for_post(self):
        opener = FakeOpener([
            {"results": [1, 2], "has_more": True, "next_cursor": "c2"},
            {"results": [3], "has_more": False, "next_cursor": None},
        ])
        c = NotionClient("tok", opener=opener, sleep=lambda s: None, min_interval=0)
        self.assertEqual(list(c.search()), [1, 2, 3])
        second_body = json.loads(opener.seen[1][2].decode("utf-8"))
        self.assertEqual(second_body["start_cursor"], "c2")
        self.assertEqual(second_body["sort"], {"direction": "descending", "timestamp": "last_edited_time"})

    def test_paginate_uses_query_string_for_get(self):
        opener = FakeOpener([
            {"results": [{"id": "a"}], "has_more": True, "next_cursor": "zz"},
            {"results": [{"id": "b"}], "has_more": False},
        ])
        c = NotionClient("tok", opener=opener, sleep=lambda s: None, min_interval=0)
        self.assertEqual([b["id"] for b in c.children("blk")], ["a", "b"])
        self.assertIn("start_cursor=zz", opener.seen[1][1])
        self.assertIn("/blocks/blk/children", opener.seen[1][1])

    def test_pacing_sleeps_between_requests(self):
        slept = []
        opener = FakeOpener([{}, {}])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0.5)
        c.request("GET", "/a")
        c.request("GET", "/b")
        self.assertTrue(any(s > 0 for s in slept))

    def test_download_sends_no_auth_header(self):
        seen = []

        def open_raw(req, timeout=0):
            seen.append(dict(req.header_items()))
            return Resp(b"bytes")

        c = NotionClient("tok", opener=open_raw, sleep=lambda s: None, min_interval=0)
        self.assertEqual(c.download("https://files.example/x.png?sig=1"), b"bytes")
        self.assertNotIn("Authorization", seen[0])


if __name__ == "__main__":
    unittest.main()
