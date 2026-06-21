"""
wiki_writer.py
Creates and updates Azure DevOps Wiki pages via REST API.
"""
from __future__ import annotations
import base64
import json
import urllib.parse
import urllib.request


class WikiWriter:
    def __init__(self, org: str, project: str, wiki_id: str, pat: str):
        self.org = org.rstrip("/")
        self.project = urllib.parse.quote(project)
        self.wiki_id = wiki_id
        self._auth = base64.b64encode(f":{pat}".encode()).decode()
        self._base = f"{self.org}/{self.project}/_apis/wiki/wikis/{wiki_id}"

    def _headers(self, extra: dict = None) -> dict:
        h = {
            "Authorization": f"Basic {self._auth}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, url: str, body: dict = None, extra_headers: dict = None) -> dict:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(extra_headers), method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e

    def page_exists(self, path: str) -> tuple[bool, str | None]:
        """Check if page exists. Returns (exists, etag)."""
        encoded = urllib.parse.quote(path, safe="")
        url = f"{self._base}/pages?path={encoded}&api-version=7.1"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                etag = r.headers.get("ETag", "")
                return True, etag
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, None
            raise

    def create_page(self, path: str, content: str) -> dict:
        """Create a new wiki page."""
        encoded = urllib.parse.quote(path, safe="")
        url = f"{self._base}/pages?path={encoded}&api-version=7.1"
        return self._request("PUT", url, {"content": content})

    def update_page(self, path: str, content: str) -> dict:
        """Update an existing wiki page (fetches ETag automatically)."""
        exists, etag = self.page_exists(path)
        if not exists:
            return self.create_page(path, content)
        encoded = urllib.parse.quote(path, safe="")
        url = f"{self._base}/pages?path={encoded}&api-version=7.1"
        return self._request("PUT", url, {"content": content},
                             extra_headers={"If-Match": etag or "*"})

    def create_or_update(self, path: str, content: str) -> dict:
        """Create if not exists, update if exists."""
        exists, _ = self.page_exists(path)
        if exists:
            return self.update_page(path, content)
        return self.create_page(path, content)
