import logging
import re
import time
import urllib.parse
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)


class WebSearchService:
    """
    Free web search using DuckDuckGo HTML interface (no API key required).
    Returns a list of results with title, link, and snippet.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
            "Referer": "https://duckduckgo.com/",
        })


    def search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "vn-vi",
    ) -> List[Dict[str, str]]:
        """
        Search DuckDuckGo and return top results.

        Each result is a dict: {"title": str, "link": str, "snippet": str}
        """
        if not query or not query.strip():
            return []

        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://lite.duckduckgo.com/lite/?q={encoded}&kl={region}"
            logger.info(f"DuckDuckGo search: {query[:80]}")

            r = self.session.get(url, timeout=(10, 20))
            if r.status_code != 200:
                logger.warning(f"DuckDuckGo returned {r.status_code}: {r.text[:200]}")
                return []

            return self._parse_results(r.text, max_results)

        except Exception as e:
            logger.exception(f"DuckDuckGo search failed for query: {query[:80]}")
            return []

    def _parse_results(self, html: str, max_results: int) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        # Split on each result-link anchor; the following chunk has title and snippet.
        chunks = re.split(r"(<a[^>]*class='result-link'[^>]*>)", html, flags=re.IGNORECASE)

        for i in range(1, len(chunks), 2):
            if i + 1 >= len(chunks):
                break
            link_tag = chunks[i]
            body = chunks[i + 1]

            link_match = re.search(r"href=\"([^\"]+)\"", link_tag)
            if not link_match:
                continue
            link = link_match.group(1)

            # Decode DuckDuckGo redirect URL: //duckduckgo.com/l/?uddg=<encoded>&amp;rut=...
            uddg = re.search(r"uddg=([^&]+)", link)
            if uddg:
                link = urllib.parse.unquote(uddg.group(1))

            title_match = re.search(r"^(.*?)</a>", body, re.DOTALL | re.IGNORECASE)
            title = self._strip_html(title_match.group(1)) if title_match else ""

            # Snippet may be in a following row with class='result-snippet'
            snippet_match = re.search(r"<td[^>]*class='result-snippet'[^>]*>(.*?)</td>", body, re.DOTALL | re.IGNORECASE)
            snippet = self._strip_html(snippet_match.group(1)) if snippet_match else ""

            if title and link:
                results.append({"title": title, "link": link, "snippet": snippet})
            if len(results) >= max_results:
                break

        logger.info(f"DuckDuckGo returned {len(results)} results")
        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        return urllib.parse.unquote(text).strip()

    def fetch_page_text(self, url: str, max_chars: int = 2000) -> str:
        """Fetch a webpage and return extracted text (best effort)."""
        try:
            r = self.session.get(url, timeout=(8, 15))
            if r.status_code != 200:
                return ""
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return ""


web_search_service = WebSearchService()
