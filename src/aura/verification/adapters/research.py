from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup


@dataclass
class ResearchResult:
    title: str
    url: str
    source: str
    snippet: str


class ResearchAgent:
    def __init__(self, timeout_seconds: int = 25) -> None:
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        }
    def research_web(self, query: str, required_terms: list[str], max_results: int = 8) -> list[dict]:
        base_query = query.strip()
        if not base_query:
            return []

        discovered: list[dict] = []
        seen_urls: set[str] = set()

        links = self._duckduckgo_links(base_query)
        for title, url in links:
            if url in seen_urls:
                continue
            if not self._is_http_url(url):
                continue

            page_text = self._fetch_page_text(url)
            if not page_text:
                continue

            lower_text = page_text.lower()
            terms_ok = all(term.lower() in lower_text for term in required_terms)
            if required_terms and not terms_ok and not all(term.lower() in title.lower() for term in required_terms):
                continue

            snippet = self._best_snippet(page_text, required_terms[0] if required_terms else query)
            discovered.append(
                {
                    "title": self._clean_space(title) or "Web result",
                    "url": url,
                    "source": urlparse(url).netloc,
                    "snippet": snippet,
                }
            )
            seen_urls.add(url)

            if len(discovered) >= max_results:
                return discovered

        return discovered

    def _duckduckgo_links(self, query: str) -> list[tuple[str, str]]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout_seconds)
            response.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(response.text, "lxml")
        anchors = soup.select("a.result__a")
        out: list[tuple[str, str]] = []
        for a in anchors[:12]:
            title = self._clean_space(a.get_text(" ", strip=True))
            href = (a.get("href") or "").strip()
            if title and href:
                out.append((title, href))
        return out

    def _fetch_page_text(self, url: str) -> str:
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout_seconds)
            response.raise_for_status()
        except Exception:
            return ""

        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()

        text = soup.get_text(" ", strip=True)
        return self._clean_space(text)[:40000]

    def _best_snippet(self, text: str, needle: str) -> str:
        if not text:
            return ""
        if not needle:
            return text[:220]

        lower = text.lower()
        idx = lower.find(needle.lower())
        if idx == -1:
            idx = lower.find("hackathon")
        if idx == -1:
            return text[:220]

        start = max(0, idx - 90)
        end = min(len(text), idx + 160)
        return self._clean_space(text[start:end])

    def _is_http_url(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    def _clean_space(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
