import os
import re
import json
import gzip
import io
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional


class WebSearchManager:
    """Fast, reliable web search and content extraction manager for LLM agents.

    Supports:
    1. Tavily AI (TAVILY_API_KEY) - LLM-native search & page extraction
    2. Serper.dev (SERPER_API_KEY) - Fast Google SERP JSON API
    3. Brave Search (BRAVE_API_KEY) - Privacy-focused web index
    4. Multi-Layer Keyless Fallback (DDG HTML -> DDG Instant API -> Wikipedia Search)
    """

    def __init__(self, tavily_key: Optional[str] = None,
                 serper_key: Optional[str] = None,
                 brave_key: Optional[str] = None):
        self.tavily_key = tavily_key or os.getenv("TAVILY_API_KEY")
        self.serper_key = serper_key or os.getenv("SERPER_API_KEY")
        self.brave_key = brave_key or os.getenv("BRAVE_API_KEY")

    def search(self, query: str, max_results: int = 5, include_raw_content: bool = False) -> str:
        """Execute a web search using the best available provider."""
        query = query.strip().strip("'\"")
        if not query:
            return "ERROR: Please provide a search query."

        # 1. Try Tavily (LLM-native)
        if self.tavily_key:
            res = self._search_tavily(query, max_results, include_raw_content)
            if res and not res.startswith("ERROR"):
                return res

        # 2. Try Serper.dev (Google SERP)
        if self.serper_key:
            res = self._search_serper(query, max_results)
            if res and not res.startswith("ERROR"):
                return res

        # 3. Try Brave Search
        if self.brave_key:
            res = self._search_brave(query, max_results)
            if res and not res.startswith("ERROR"):
                return res

        # 4. Fallback to Multi-layer keyless search
        return self._search_keyless_fallback(query, max_results)

    def _search_tavily(self, query: str, max_results: int = 5, include_raw_content: bool = False) -> str:
        """Execute search using Tavily API."""
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.tavily_key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": include_raw_content,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            lines = [f"## Web Search Results for '{query}' (via Tavily)"]

            if result.get("answer"):
                lines.append(f"\n### Direct Answer:\n{result['answer']}\n")

            results = result.get("results", [])
            for i, item in enumerate(results, 1):
                lines.append(f"### {i}. [{item.get('title', 'Untitled')}]({item.get('url', '')})")
                if item.get("snippet"):
                    lines.append(f"{item['snippet']}\n")
                if include_raw_content and item.get("raw_content"):
                    raw = item["raw_content"][:1000]
                    lines.append(f"```\n{raw}...\n```\n")

            return "\n".join(lines)
        except Exception as e:
            return f"ERROR: Tavily search failed: {e}"

    def _search_serper(self, query: str, max_results: int = 5) -> str:
        """Execute search using Serper.dev (Google SERP)."""
        try:
            url = "https://google.serper.dev/search"
            payload = {"q": query, "num": max_results}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            lines = [f"## Web Search Results for '{query}' (via Serper/Google)"]

            if "answerBox" in result:
                ab = result["answerBox"]
                ans = ab.get("answer") or ab.get("snippet") or str(ab)
                lines.append(f"\n### Answer Box:\n{ans}\n")

            organic = result.get("organic", [])
            for i, item in enumerate(organic[:max_results], 1):
                lines.append(f"### {i}. [{item.get('title', 'Untitled')}]({item.get('link', '')})")
                if item.get("snippet"):
                    lines.append(f"{item['snippet']}\n")

            return "\n".join(lines)
        except Exception as e:
            return f"ERROR: Serper search failed: {e}"

    def _search_brave(self, query: str, max_results: int = 5) -> str:
        """Execute search using Brave Search API."""
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count={max_results}"
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.brave_key,
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            lines = [f"## Web Search Results for '{query}' (via Brave)"]
            web_results = result.get("web", {}).get("results", [])

            for i, item in enumerate(web_results[:max_results], 1):
                lines.append(f"### {i}. [{item.get('title', 'Untitled')}]({item.get('url', '')})")
                if item.get("description"):
                    lines.append(f"{item['description']}\n")

            return "\n".join(lines)
        except Exception as e:
            return f"ERROR: Brave search failed: {e}"

    def _search_keyless_fallback(self, query: str, max_results: int = 5) -> str:
        """Multi-layer keyless search fallback combining DDG HTML, DDG API, and Wikipedia Search."""
        # Layer 1: DDG HTML Search
        ddg_html_res = self._search_duckduckgo_html(query, max_results)
        if ddg_html_res and not ddg_html_res.startswith("No results"):
            return ddg_html_res

        # Layer 2: DDG Instant Answer API
        ddg_api_res = self._search_duckduckgo_api(query, max_results)
        if ddg_api_res and not ddg_api_res.startswith("No results"):
            return ddg_api_res

        # Layer 3: Wikipedia Search API
        wiki_res = self._search_wikipedia_api(query, max_results)
        if wiki_res and not wiki_res.startswith("No results"):
            return wiki_res

        return f"No results found for query '{query}' across keyless providers."

    def _search_duckduckgo_html(self, query: str, max_results: int = 5) -> str:
        """Keyless search using DuckDuckGo HTML."""
        try:
            url = "https://html.duckduckgo.com/html/"
            data = urllib.parse.urlencode({"q": query}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/115.0.0.0 Safari/537.36"
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.getcode() != 200:
                    return f"No results found for query '{query}'."
                html = resp.read().decode("utf-8", errors="replace")

            snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)

            if not snippets:
                return f"No results found for query '{query}'."

            lines = [f"## Web Search Results for '{query}' (via DuckDuckGo)"]

            count = min(len(snippets), max_results)
            for i in range(count):
                link, snippet_raw = snippets[i]
                title_raw = titles[i][1] if i < len(titles) else "Result"

                if "uddg=" in link:
                    m = re.search(r"uddg=([^&]+)", link)
                    if m:
                        link = urllib.parse.unquote(m.group(1))

                snippet_clean = re.sub(r"<[^>]+>", "", snippet_raw).strip()
                title_clean = re.sub(r"<[^>]+>", "", title_raw).strip()

                lines.append(f"### {i+1}. [{title_clean}]({link})")
                lines.append(f"{snippet_clean}\n")

            return "\n".join(lines)
        except Exception:
            return f"No results found for query '{query}'."

    def _search_duckduckgo_api(self, query: str, max_results: int = 5) -> str:
        """Keyless search using DuckDuckGo Instant Answer API."""
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                res = json.loads(resp.read().decode("utf-8"))

            lines = [f"## Web Search Results for '{query}' (via DuckDuckGo Instant API)"]

            if res.get("AbstractText"):
                lines.append(f"\n### Summary:\n{res['AbstractText']}\nURL: {res.get('AbstractURL', '')}\n")

            topics = res.get("RelatedTopics", [])
            added = 0
            for t in topics:
                if added >= max_results:
                    break
                if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
                    added += 1
                    lines.append(f"### {added}. [{t.get('Text')[:60]}...]({t.get('FirstURL')})")
                    lines.append(f"{t.get('Text')}\n")

            if len(lines) == 1:
                return f"No results found for query '{query}'."

            return "\n".join(lines)
        except Exception:
            return f"No results found for query '{query}'."

    def _search_wikipedia_api(self, query: str, max_results: int = 5) -> str:
        """Keyless search using Wikipedia Search API."""
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                res = json.loads(resp.read().decode("utf-8"))

            items = res.get("query", {}).get("search", [])
            if not items:
                return f"No results found for query '{query}'."

            lines = [f"## Web Search Results for '{query}' (via Wikipedia)"]
            for i, item in enumerate(items[:max_results], 1):
                title = item.get("title", "")
                page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                snippet = re.sub(r"<[^>]+>", "", item.get("snippet", "")).strip()

                lines.append(f"### {i}. [{title}]({page_url})")
                lines.append(f"{snippet}\n")

            return "\n".join(lines)
        except Exception:
            return f"No results found for query '{query}'."

    def fetch_page(self, url: str, max_chars: int = 4000) -> str:
        """Fetch a webpage URL and extract clean text/markdown."""
        url = url.strip().strip("'\"")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        try:
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
                content_type = resp.headers.get("Content-Type", "").lower()
                content_encoding = resp.headers.get("Content-Encoding", "").lower()
                raw_bytes = resp.read()

                if "gzip" in content_encoding:
                    try:
                        raw_bytes = gzip.decompress(raw_bytes)
                    except Exception:
                        pass
                elif "deflate" in content_encoding:
                    try:
                        import zlib
                        raw_bytes = zlib.decompress(raw_bytes)
                    except Exception:
                        pass

                html = raw_bytes.decode("utf-8", errors="replace")

            # Convert HTML to clean text/markdown
            text = self._html_to_clean_text(html)

            lines = [
                f"## Content from: {url}",
                f"- Content-Type: {content_type}",
                f"- Extracted length: {len(text)} characters",
                "```markdown",
                text[:max_chars] + ("\n... [truncated]" if len(text) > max_chars else ""),
                "```",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"ERROR fetching web page '{url}': {e}"

    def _html_to_clean_text(self, html: str) -> str:
        """Strip scripts, styles, tags, and collapse blank spaces from HTML."""
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

    def search_code_docs(self, query: str, topic: str = "python") -> str:
        """Targeted documentation search for libraries and code frameworks."""
        targeted_query = f"{topic} documentation {query}"
        return self.search(targeted_query, max_results=5)
