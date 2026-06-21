"""
wiki_reader.py
Reads pages from Azure DevOps Wiki via REST API.
"""
from __future__ import annotations
import base64
import urllib.parse
import urllib.request
import json
import os


class WikiReader:
    def __init__(self, org: str, project: str, wiki_id: str, pat: str):
        self.org = org.rstrip("/")
        self.project = urllib.parse.quote(project)
        self.wiki_id = wiki_id
        self._auth = base64.b64encode(f":{pat}".encode()).decode()
        self._base = f"{self.org}/{self.project}/_apis/wiki/wikis/{wiki_id}"

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {self._auth}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def list_pages(self) -> list[str]:
        """Return flat list of all page paths."""
        data = self._get(f"{self._base}/pages?recursionLevel=full&api-version=7.1")
        paths = []
        def collect(node):
            paths.append(node["path"])
            for sub in node.get("subPages", []):
                collect(sub)
        collect(data)
        return paths

    def get_page(self, path: str) -> str:
        """Return markdown content of a wiki page."""
        encoded = urllib.parse.quote(path, safe="")
        url = f"{self._base}/pages?path={encoded}&includeContent=true&api-version=7.1"
        data = self._get(url)
        return data.get("content", "")

    def get_page_meta(self, path: str) -> dict:
        """Return metadata (id, etag, path) of a page."""
        encoded = urllib.parse.quote(path, safe="")
        url = f"{self._base}/pages?path={encoded}&api-version=7.1"
        return self._get(url)

    def search_pages(self, keyword: str) -> list[str]:
        """Return paths of pages whose path contains the keyword (case-insensitive)."""
        kw = keyword.lower()
        return [p for p in self.list_pages() if kw in p.lower()]

    def get_related_pages(self, keywords: list[str]) -> list[dict]:
        """Get content snippets of pages related to any of the keywords."""
        all_paths = self.list_pages()
        results = []
        for kw in keywords:
            kw_lower = kw.lower()
            matches = [p for p in all_paths if kw_lower in p.lower()][:2]
            for path in matches:
                try:
                    content = self.get_page(path)
                    results.append({
                        "path": path,
                        "snippet": content[:400],
                        "link": self._wiki_link(path),
                    })
                except Exception:
                    pass
        return results

    def _wiki_link(self, path: str) -> str:
        org_name = self.org.split("dev.azure.com/")[-1]
        proj = urllib.parse.unquote(self.project)
        encoded = urllib.parse.quote(path, safe="/")
        return f"{self.org}/{proj}/_wiki/wikis/{self.wiki_id}?pagePath={encoded}"
