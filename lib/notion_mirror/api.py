"""The only module that talks HTTP. Paced, retrying, paginating, and nothing else.

Rate limit: Notion averages about three requests a second per integration. A fixed
minimum interval between requests keeps a full walk under that without bursts;
429 and 5xx retry with Retry-After (or exponential backoff), other 4xx fail at once.

A 403 is special: Notion itself returns a JSON body with an "object": "error" key
for a real permission refusal, but heavy traffic can draw a Cloudflare (or other
CDN) challenge page instead, an HTML 403 that has nothing to do with permissions
and clears up after it cools down. A 403 with a non-JSON, non-Notion body is
treated as a challenge and retried with a long backoff; a 403 with a genuine
Notion error body still fails at once.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, List, Optional

from .config import DEFAULT_VERSION

API = "https://api.notion.com/v1"


class NotionError(RuntimeError):
    """A request that failed after retries, or a hard 4xx. The message names the call."""


def _is_notion_error_body(text: str) -> bool:
    """True only for a real Notion API error: JSON with an "object": "error" key."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("object") == "error"


class NotionClient:
    def __init__(self, token: str, version: str = DEFAULT_VERSION, min_interval: float = 0.34,
                 opener=None, sleep=time.sleep, retries: int = 5, challenge_backoff: float = 30.0):
        self._token = token
        self._version = version
        self._min = min_interval
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._retries = retries
        self._challenge_backoff = challenge_backoff
        self._last = 0.0
        self.requests = 0

    # -- plumbing -----------------------------------------------------------------

    def _pace(self) -> None:
        now = time.monotonic()
        wait = self._last + self._min - now
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    def request(self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self._token,
            "Notion-Version": self._version,
            "Content-Type": "application/json",
        }
        last_error = "no attempts"
        for attempt in range(self._retries + 1):
            self._pace()
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._open(req, timeout=60) as resp:
                    self.requests += 1
                    raw = resp.read().decode("utf-8")
                    try:
                        return json.loads(raw)
                    except ValueError:
                        raise NotionError("%s %s: unreadable body: %s" % (method, path, raw[:300]))
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", errors="replace")[:300]
                challenge = exc.code == 403 and not _is_notion_error_body(text)
                if challenge:
                    last_error = "HTTP 403 (challenge page): %s" % text
                else:
                    last_error = "HTTP %s: %s" % (exc.code, text)
                if exc.code == 429 or exc.code >= 500 or challenge:
                    if attempt < self._retries:
                        retry_after = exc.headers.get("Retry-After") if exc.headers else None
                        if retry_after:
                            wait = float(retry_after)
                        elif challenge:
                            wait = self._challenge_backoff * (attempt + 1)
                        else:
                            wait = float(2 ** attempt)
                        self._sleep(wait)
                        continue
                raise NotionError("%s %s: %s" % (method, path, last_error))
            except (urllib.error.URLError, OSError) as exc:
                last_error = str(exc)
                if attempt < self._retries:
                    self._sleep(float(2 ** attempt))
                    continue
        raise NotionError("%s %s: gave up after %d retries: %s" % (method, path, self._retries, last_error))

    def paginate(self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Iterator[dict]:
        cursor = None
        while True:
            b = dict(body or {})
            p = dict(params or {})
            if cursor:
                if method == "POST":
                    b["start_cursor"] = cursor
                else:
                    p["start_cursor"] = cursor
            page = self.request(method, path, b if method == "POST" else None, p or None)
            for item in page.get("results", []):
                yield item
            if not page.get("has_more"):
                return
            cursor = page.get("next_cursor")
            if not cursor:
                return

    # -- the calls the mirror makes ----------------------------------------------

    def search(self, object_type: Optional[str] = None) -> Iterator[dict]:
        """Every page and data source the integration can see, newest edit first."""
        body: Dict[str, object] = {"page_size": 100, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
        if object_type:
            body["filter"] = {"property": "object", "value": object_type}
        return self.paginate("POST", "/search", body)

    def page(self, page_id: str) -> dict:
        return self.request("GET", "/pages/%s" % page_id)

    def block(self, block_id: str) -> dict:
        return self.request("GET", "/blocks/%s" % block_id)

    def data_source(self, ds_id: str) -> dict:
        return self.request("GET", "/data_sources/%s" % ds_id)

    def database(self, db_id: str) -> dict:
        return self.request("GET", "/databases/%s" % db_id)

    def query_rows(self, ds_id: str) -> Iterator[dict]:
        return self.paginate("POST", "/data_sources/%s/query" % ds_id, {"page_size": 100})

    def children(self, block_id: str) -> List[dict]:
        return list(self.paginate("GET", "/blocks/%s/children" % block_id, params={"page_size": 100}))

    def download(self, url: str) -> bytes:
        """Fetch a signed file URL. No auth header: the signature is the credential."""
        self._pace()
        req = urllib.request.Request(url, method="GET")
        try:
            with self._open(req, timeout=120) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise NotionError("download %s: %s" % (url.split("?")[0], exc))
