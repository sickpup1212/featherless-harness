import os
import re
import json
import asyncio
import urllib.parse
from typing import List, Dict, Any, Optional

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_INSTALLED = True
except ImportError:
    CRAWL4AI_INSTALLED = False


class Crawl4AIToolkit:
    """Asynchronous Web Crawling Toolkit for LLM Agents using Crawl4AI or Async Fallback.

    Provides high-speed async web crawling, markdown extraction, deep crawling,
    and structured content extraction.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    async def crawl_url(self, url: str, word_count_threshold: int = 10, max_chars: int = 5000) -> str:
        """Asynchronously crawl a URL and convert page content into clean Markdown."""
        url = url.strip().strip("'\"")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        if CRAWL4AI_INSTALLED:
            try:
                async with AsyncWebCrawler(verbose=self.verbose) as crawler:
                    result = await crawler.arun(url=url, word_count_threshold=word_count_threshold)
                    markdown_content = result.markdown or result.cleaned_html or ""

                    lines = [
                        f"## Crawled URL: {url} (via Crawl4AI)",
                        f"- Success: {result.success}",
                        f"- Status Code: {getattr(result, 'status_code', 200)}",
                        "```markdown",
                        markdown_content[:max_chars] + ("\n... [truncated]" if len(markdown_content) > max_chars else ""),
                        "```"
                    ]
                    return "\n".join(lines)
            except Exception as e:
                if self.verbose:
                    print(f"Crawl4AI failed: {e}, falling back to async HTTP crawler")

        # Async HTTP Fallback
        return await self._async_fallback_crawl(url, max_chars=max_chars)

    async def _async_fallback_crawl(self, url: str, max_chars: int = 5000) -> str:
        """Async fallback crawler when crawl4ai library is not installed."""
        loop = asyncio.get_running_loop()
        def _fetch():
            import urllib.request, gzip
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/115.0.0.0 Safari/537.36"
                    ),
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                encoding = resp.headers.get("Content-Encoding", "").lower()
                raw = resp.read()
                if "gzip" in encoding:
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                return raw.decode("utf-8", errors="replace")

        try:
            html = await loop.run_in_executor(None, _fetch)
            text = self._clean_html_to_markdown(html)

            lines = [
                f"## Crawled URL: {url} (via Async Fallback)",
                f"- Extracted length: {len(text)} characters",
                "```markdown",
                text[:max_chars] + ("\n... [truncated]" if len(text) > max_chars else ""),
                "```"
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"ERROR crawling URL '{url}': {e}"

    async def deep_crawl(self, start_url: str, max_pages: int = 5, max_depth: int = 2) -> str:
        """Asynchronously crawl a domain starting from start_url up to max_pages."""
        start_url = start_url.strip().strip("'\"")
        if not start_url.startswith("http://") and not start_url.startswith("https://"):
            start_url = "https://" + start_url

        parsed_start = urllib.parse.urlparse(start_url)
        domain = parsed_start.netloc

        visited = set()
        queue = [(start_url, 1)]
        results = []

        while queue and len(visited) < max_pages:
            curr_url, depth = queue.pop(0)
            if curr_url in visited or depth > max_depth:
                continue

            visited.add(curr_url)
            page_summary = await self.crawl_url(curr_url, max_chars=1000)
            results.append(f"### Page {len(visited)}: {curr_url}\n{page_summary}\n")

            # Extract internal domain links if depth < max_depth
            if depth < max_depth:
                internal_links = self._extract_domain_links(page_summary, curr_url, domain)
                for link in internal_links:
                    if link not in visited and len(visited) + len(queue) < max_pages:
                        queue.append((link, depth + 1))

        lines = [
            f"## Deep Crawl Results for Domain '{domain}'",
            f"- Total Pages Crawled: {len(visited)}",
            f"- Max Depth Explored: {max_depth}",
            "",
            "\n---\n".join(results)
        ]
        return "\n".join(lines)

    async def extract_structured_data(self, url: str, schema_description: str = "") -> str:
        """Asynchronously crawl a page and format structured content or JSON."""
        content = await self.crawl_url(url, max_chars=6000)
        lines = [
            f"## Structured Data Extraction for: {url}",
            f"- Schema Target: {schema_description or 'General Article / Specs'}",
            "",
            content
        ]
        return "\n".join(lines)

    def _clean_html_to_markdown(self, html: str) -> str:
        """Convert HTML string to clean readable Markdown text."""
        text = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n\n# \1\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li>", "\n- ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        lines = [line.strip() for line in text.splitlines()]
        clean_lines = []
        for line in lines:
            if line or (clean_lines and clean_lines[-1]):
                clean_lines.append(line)
        return "\n".join(clean_lines).strip()

    def _extract_domain_links(self, page_content: str, base_url: str, domain: str) -> List[str]:
        """Extract links within the same domain from page content."""
        links = set()
        raw_links = re.findall(r'https?://[^\s\)"\'>]+', page_content)
        for link in raw_links:
            parsed = urllib.parse.urlparse(link)
            if parsed.netloc == domain and link != base_url:
                links.add(link)
        return list(links)[:10]
