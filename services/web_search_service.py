import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)


class WebSearchService:
    """
    Free web search using DuckDuckGo HTML interface (no API key required).
    Optionally uses the local `agy` CLI (which has built-in web search tooling)
    when available; falls back to DuckDuckGo scraping if agy fails or is missing.
    Returns a list of results with title, link, snippet and optional content.
    """

    AGY_MODEL = "Gemini 3.7 Flash (Medium)"
    AGY_TIMEOUT_SECONDS = 60
    AGY_TIMEOUT_DURATION = "90s"

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
        Search using agy CLI if available, otherwise fall back to DuckDuckGo.

        Each result is a dict: {"title": str, "link": str, "snippet": str}
        """
        if not query or not query.strip():
            return []

        agy_results = self._search_with_agy(query, max_results=max_results)
        if agy_results:
            return agy_results

        return self._search_with_duckduckgo(query, max_results=max_results, region=region)

    def _search_with_agy(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Use the agy CLI web-search capability.  We ask agy to answer the query
        using web search and to return a JSON array of sources it used.

        Returns [] if agy is not installed, times out, or emits no usable JSON.
        """
        agy_path = shutil.which("agy") or "/home/devops/.local/bin/agy"
        if not agy_path or not shutil.which(agy_path):
            return []

        prompt = (
            "Hãy tìm kiếm web và trả lời câu hỏi sau bằng tiếng Việt. "
            "Sau câu trả lời, hãy liệt kê các nguồn web bạn đã dùng dưới dạng JSON array, "
            "mỗi nguồn có title, link, snippet.\n\n"
            f"Câu hỏi: {query}\n\n"
            "Định dạng yêu cầu:\n"
            "<câu trả lời ngắn gọn>\n\n"
            "SOURCES:\n"
            '[{"title": "...", "link": "...", "snippet": "..."}, ...]'
        )

        try:
            result = subprocess.run(
                [
                    agy_path,
                    "--model", self.AGY_MODEL,
                    "--print-timeout", self.AGY_TIMEOUT_DURATION,
                    "-p", prompt,
                ],
                capture_output=True,
                text=True,
                timeout=self.AGY_TIMEOUT_SECONDS + 5,
            )
            output = result.stdout + "\n" + result.stderr
            logger.info(f"agy search output length: {len(output)}")
            return self._parse_agy_output(output, max_results=max_results)
        except Exception as e:
            logger.warning(f"agy search failed: {e}")
            return []

    def answer_with_agy(self, query: str, sender_name: str = "", rolling_summary: str = "") -> str:
        """
        Use the local `agy` CLI to answer the query directly.
        agy has built-in web-search tooling, so this usually returns
        current, real-world data without manual scraping.

        Returns empty string if agy is missing, times out, or errors out.
        """
        agy_path = shutil.which("agy") or "/home/devops/.local/bin/agy"
        if not agy_path or not shutil.which(agy_path):
            logger.info("agy CLI not found; skipping direct answer")
            return ""

        # Preserve the bot's persona and the way the admin should be addressed.
        addressing = ""
        if "Mai Công Sao" in sender_name or "Sao" in sender_name:
            addressing = (
                "Người đang hỏi là Admin Mai Công Sao (đại ca). "
                "Hãy xưng hô thân mật, gọi họ là đại ca, không khách sáo.\n"
            )
        else:
            addressing = f"Người đang hỏi: {sender_name}\n" if sender_name else ""

        context_block = ""
        if rolling_summary:
            context_block = f"Bối cảnh hội thoại trước đó: {rolling_summary}\n\n"

        prompt = (
            "Bạn là Bot Sao Assistant trên Zalo, trợ lý AI của Admin Mai Công Sao. "
            "Hãy tìm kiếm web và trả lời câu hỏi sau một cách ngắn gọn, chính xác, bằng tiếng Việt. "
            "Nếu có số liệu cụ thể (giá cả, nhiệt độ, tỷ số, ngày giờ...), hãy đưa ra con số. "
            "KHÔNG kết thúc bằng marker nào.\n\n"
            f"{addressing}"
            f"{context_block}"
            f"Câu hỏi: {query}"
        )

        try:
            logger.info(f"Calling agy for direct answer: {query[:80]}")
            result = subprocess.run(
                [
                    agy_path,
                    "--model", self.AGY_MODEL,
                    "--print-timeout", self.AGY_TIMEOUT_DURATION,
                    "-p", prompt,
                ],
                capture_output=True,
                text=True,
                timeout=self.AGY_TIMEOUT_SECONDS + 10,
            )
            output = result.stdout.strip()
            if not output and result.stderr:
                logger.warning(f"agy stderr: {result.stderr[:500]}")
                return ""
            logger.info(f"agy direct answer length: {len(output)}")
            return output
        except Exception as e:
            logger.warning(f"agy direct answer failed: {e}")
            return ""

    def analyze_image_with_agy(self, image_data: str, user_prompt: str = "", sender_name: str = "", rolling_summary: str = "") -> str:
        """
        Analyze an image with the agy CLI. agy reads the image via the
        `@/path/to/file` syntax that the underlying Gemini CLI supports.

        Args:
            image_data: data URL (data:image/jpeg;base64,...) or http(s) URL.
            user_prompt: user's caption/question about the image.
            sender_name: display name of the current user.
            rolling_summary: short rolling summary of the recent conversation.

        Returns empty string if agy fails or the file cannot be written.
        """
        agy_path = shutil.which("agy") or "/home/devops/.local/bin/agy"
        if not agy_path or not shutil.which(agy_path):
            logger.info("agy CLI not found; skipping image analysis")
            return ""

        tmp_path: Optional[str] = None
        try:
            tmp_path = self._save_image_to_temp(image_data)
            if not tmp_path:
                return ""

            question = user_prompt.strip() or "Hãy xem và phân tích/mô tả chi tiết bức ảnh này giúp tôi."

            addressing = ""
            if "Mai Công Sao" in sender_name or "Sao" in sender_name:
                addressing = (
                    "Người gửi là Admin Mai Công Sao (đại ca). "
                    "Hãy xưng hô thân mật, gọi họ là đại ca, không khách sáo.\n"
                )
            else:
                addressing = f"Người gửi: {sender_name}\n" if sender_name else ""

            context_block = ""
            if rolling_summary:
                context_block = f"Bối cảnh hội thoại trước đó: {rolling_summary}\n\n"

            prompt = (
                "Bạn là Bot Sao Assistant trên Zalo, trợ lý AI của Admin Mai Công Sao. "
                "Hãy phân tích bức ảnh được đính kèm và trả lời yêu cầu bên dưới bằng tiếng Việt, ngắn gọn. "
                "KHÔNG kết thúc bằng marker nào.\n\n"
                f"{addressing}"
                f"{context_block}"
                f"Ảnh: @{tmp_path}\n\n"
                f"Yêu cầu của người dùng: {question}"
            )

            logger.info("Calling agy for image analysis")
            result = subprocess.run(
                [
                    agy_path,
                    "--model", self.AGY_MODEL,
                    "--print-timeout", self.AGY_TIMEOUT_DURATION,
                    "-p", prompt,
                ],
                capture_output=True,
                text=True,
                timeout=self.AGY_TIMEOUT_SECONDS + 10,
            )
            output = result.stdout.strip()
            if not output and result.stderr:
                logger.warning(f"agy image stderr: {result.stderr[:500]}")
                return ""
            logger.info(f"agy image answer length: {len(output)}")
            return output
        except Exception as e:
            logger.warning(f"agy image analysis failed: {e}")
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _save_image_to_temp(self, image_data: str) -> Optional[str]:
        """Persist the image to a temp file so agy can read it with @path."""
        try:
            image_bytes: Optional[bytes] = None
            suffix = ".jpg"
            if image_data.startswith("data:"):
                header, b64 = image_data.split(";base64,", 1)
                mime = header.replace("data:", "")
                if "png" in mime:
                    suffix = ".png"
                elif "webp" in mime:
                    suffix = ".webp"
                image_bytes = base64.b64decode(b64)
            elif image_data.startswith("http"):
                resp = self.session.get(image_data, timeout=(10, 20))
                if resp.status_code != 200:
                    return None
                image_bytes = resp.content

            if not image_bytes:
                return None

            fd, tmp_path = tempfile.mkstemp(prefix="agy_img_", suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(image_bytes)
            return tmp_path
        except Exception as e:
            logger.warning(f"Failed to persist image for agy: {e}")
            return None

    def _parse_agy_output(self, output: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Extract the SOURCES JSON array from agy output (legacy parsing)."""
        # Find the JSON array after SOURCES:
        marker_match = re.search(r"SOURCES:\s*(\[.*?\])", output, re.DOTALL)
        if not marker_match:
            # Try the last JSON array in the output
            arrays = re.findall(r"\[.*?\]", output, re.DOTALL)
            if not arrays:
                return []
            candidate = arrays[-1]
        else:
            candidate = marker_match.group(1)

        try:
            data = json.loads(candidate)
            if not isinstance(data, list):
                return []
            results = []
            for item in data[:max_results]:
                if isinstance(item, dict) and item.get("link"):
                    results.append({
                        "title": str(item.get("title", "")),
                        "link": str(item.get("link", "")),
                        "snippet": str(item.get("snippet", "")),
                    })
            if results:
                logger.info(f"agy returned {len(results)} sources")
                return results
        except Exception as e:
            logger.warning(f"Failed to parse agy JSON output: {e}")
        return []

    def _search_with_duckduckgo(
        self,
        query: str,
        max_results: int = 5,
        region: str = "vn-vi",
    ) -> List[Dict[str, str]]:
        """
        Search DuckDuckGo HTML interface and return top results.
        """

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

    def search_with_content(
        self,
        query: str,
        max_results: int = 5,
        fetch_top_n: int = 2,
        max_chars_per_page: int = 2000,
        region: str = "vn-vi",
    ) -> List[Dict[str, str]]:
        """
        Search DuckDuckGo and fetch full text from the top `fetch_top_n` result pages.

        Each result dict now also contains "content" with the extracted page text.
        """
        results = self.search(query, max_results=max_results, region=region)
        if not results:
            return results

        for idx, result in enumerate(results[:fetch_top_n], 1):
            link = result.get("link", "")
            if not link:
                continue
            logger.info(f"Fetching page {idx}/{fetch_top_n}: {link[:120]}")
            content = self.fetch_page_text(link, max_chars=max_chars_per_page)
            result["content"] = content
            # Small polite delay between fetches
            time.sleep(0.3)

        return results


web_search_service = WebSearchService()
