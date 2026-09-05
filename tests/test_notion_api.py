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


def http_error_html(code, headers=None):
    """A Cloudflare (or any other) challenge page: not JSON, so not a Notion error body."""
    body = b"<html><head><title>Attention Required! | Cloudflare</title></head><body>Attention Required!</body></html>"
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "err", headers or {}, io.BytesIO(body))


def http_error_notion(code, headers=None):
    """A real Notion API error body: JSON with an "object": "error" key."""
    body = json.dumps({"object": "error", "status": code, "code": "restricted_resource", "message": "no access"}).encode("utf-8")
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "err", headers or {}, io.BytesIO(body))


def http_error_notion_long(code, headers=None):
    """A real Notion API error body shaped like the ones that carry additional_data: past 300 characters."""
    body = json.dumps({
        "object": "error",
        "status": code,
        "code": "restricted_resource",
        "message": "The integration does not have access to this resource. " * 3,
        "additional_data": {"pad": "x" * 400},
    }).encode("utf-8")
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "err", headers or {}, io.BytesIO(body))


def http_error_html_long(code, headers=None):
    """A challenge page padded well past 300 characters, like a real Cloudflare interstitial."""
    body = ("<html><head><title>Attention Required! | Cloudflare</title></head><body>"
            + ("Attention Required! " * 30) + "</body></html>").encode("utf-8")
    return urllib.error.HTTPError("https://api.notion.com/v1/x", code, "err", headers or {}, io.BytesIO(body))


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

    def test_403_challenge_page_retries_with_challenge_backoff(self):
        slept = []
        opener = FakeOpener([http_error_html(403), {"ok": True}])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0, challenge_backoff=30.0)
        self.assertEqual(c.request("GET", "/pages/x"), {"ok": True})
        self.assertIn(30.0, slept)

    def test_403_notion_error_body_is_immediate(self):
        slept = []
        opener = FakeOpener([http_error_notion(403)])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0)
        with self.assertRaises(NotionError):
            c.request("GET", "/pages/x")
        self.assertEqual(slept, [])
        self.assertEqual(len(opener.script), 0)

    def test_403_notion_error_body_longer_than_300_chars_is_still_immediate(self):
        slept = []
        opener = FakeOpener([http_error_notion_long(403)])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0)
        with self.assertRaises(NotionError):
            c.request("GET", "/pages/x")
        self.assertEqual(slept, [])
        self.assertEqual(len(opener.script), 0)

    def test_403_html_challenge_longer_than_300_chars_still_retries(self):
        slept = []
        opener = FakeOpener([http_error_html_long(403), {"ok": True}])
        c = NotionClient("tok", opener=opener, sleep=slept.append, min_interval=0, challenge_backoff=30.0)
        self.assertEqual(c.request("GET", "/pages/x"), {"ok": True})
        self.assertIn(30.0, slept)

    def test_five_challenge_pages_in_a_row_gives_up_naming_the_challenge(self):
        opener = FakeOpener([http_error_html(403)] * 5)
        c = NotionClient("tok", opener=opener, sleep=lambda s: None, retries=4, min_interval=0, challenge_backoff=0.01)
        with self.assertRaises(NotionError) as ctx:
            c.request("GET", "/pages/x")
        self.assertIn("challenge page", str(ctx.exception))

    def test_200_with_unparseable_body_is_a_notion_error(self):
        def open_raw(req, timeout=0):
            return Resp(b"not json")

        c = NotionClient("tok", opener=open_raw, sleep=lambda s: None, min_interval=0)
        with self.assertRaises(NotionError) as ctx:
            c.request("GET", "/pages/x")
        self.assertIn("unreadable body", str(ctx.exception))

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
