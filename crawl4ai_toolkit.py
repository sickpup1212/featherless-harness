import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Union

from crawl4ai import (
    AdaptiveConfig,
    AdaptiveCrawler,
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    DomainMapper,
    DomainMapperConfig,
    JsonCssExtractionStrategy,
    LLMConfig,
    LLMExtractionStrategy,
    ProxyConfig,
    RegexExtractionStrategy,
    UndetectedAdapter,
    VirtualScrollConfig,
)
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.content_filter_strategy import BM25ContentFilter, PruningContentFilter
from crawl4ai.processors.pdf import PDFContentScrapingStrategy, PDFCrawlerStrategy


class Crawl4AIToolkit:
    """
    Comprehensive agentic toolkit wrapping Crawl4AI features for AI execution.
    """

    def __init__(self, default_headless: bool = True):
        self.default_headless = default_headless

    async def single_crawl_tool(
        self,
        url: str,
        enable_stealth: bool = True,
        capture_media: bool = False,
        capture_network_logs: bool = False,
        content_filter_type: Optional[str] = None,  # "pruning" or "bm25"
        filter_query: Optional[str] = None,
        js_code: Optional[str] = None,
        wait_for_selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tool 1: Crawls a single URL with optional media capture, stealth settings, 
        JavaScript execution, and markdown filtering.
        """
        browser_config = BrowserConfig(
            headless=self.default_headless,
            enable_stealth=enable_stealth
        )

        # Configure markdown generation and content filters
        markdown_generator = None
        if content_filter_type == "pruning":
            markdown_generator = DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(threshold=0.48)
            )
        elif content_filter_type == "bm25" and filter_query:
            markdown_generator = DefaultMarkdownGenerator(
                content_filter=BM25ContentFilter(query=filter_query)
            )

        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            screenshot=capture_media,
            pdf=capture_media,
            capture_network_requests=capture_network_logs,
            capture_console_messages=capture_network_logs,
            js_code=js_code,
            wait_for=wait_for_selector,
            markdown_generator=markdown_generator
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            if not result.success:
                return {"success": False, "error": result.error_message}

            raw_md = result.markdown.raw_markdown if hasattr(result.markdown, 'raw_markdown') else result.markdown
            fit_md = result.markdown.fit_markdown if hasattr(result.markdown, 'fit_markdown') else None

            return {
                "success": True,
                "url": result.url,
                "status_code": result.status_code,
                "markdown": fit_md or raw_md,
                "media": result.media if capture_media else {},
                "screenshot": result.screenshot if capture_media else None,
                "network_requests": result.network_requests if capture_network_logs else [],
                "console_messages": result.console_messages if capture_network_logs else []
            }

    async def stealth_evasion_crawl_tool(
        self,
        url: str,
        proxies: Optional[List[str]] = None,
        max_retries: int = 2,
        use_undetected_browser: bool = False
    ) -> Dict[str, Any]:
        """
        Tool 2: Bypasses anti-bot mechanisms (Cloudflare, Akamai) using proxy 
        escalation, undetected browser patches, and automatic retries.
        """
        browser_config = BrowserConfig(
            headless=False if use_undetected_browser else self.default_headless,
            enable_stealth=True
        )

        # Parse proxy strings if supplied
        proxy_configs = None
        if proxies:
            proxy_configs = [ProxyConfig.from_string(p) for p in proxies]

        run_config = CrawlerRunConfig(
            magic=True,
            wait_until="load",
            max_retries=max_retries,
            proxy_config=proxy_configs
        )

        if use_undetected_browser:
            adapter = UndetectedAdapter()
            strategy = AsyncPlaywrightCrawlerStrategy(
                browser_config=browser_config,
                browser_adapter=adapter
            )
            crawler_instance = AsyncWebCrawler(crawler_strategy=strategy, config=browser_config)
        else:
            crawler_instance = AsyncWebCrawler(config=browser_config)

        async with crawler_instance as crawler:
            result = await crawler.arun(url=url, config=run_config)
            return {
                "success": result.success,
                "url": result.url,
                "resolved_by": result.crawl_stats.get("resolved_by") if result.crawl_stats else None,
                "attempts": result.crawl_stats.get("attempts") if result.crawl_stats else 1,
                "markdown": result.markdown.raw_markdown if hasattr(result.markdown, 'raw_markdown') else result.markdown,
                "error": result.error_message
            }

    async def batch_streaming_crawl_tool(
        self,
        urls: List[str],
        memory_threshold_percent: float = 75.0,
        max_concurrent: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Tool 3: Concurrently crawls multiple URLs with memory-adaptive throttling 
        to prevent resource exhaustion.
        """
        dispatcher = MemoryAdaptiveDispatcher(
            memory_threshold_percent=memory_threshold_percent,
            max_session_permit=max_concurrent
        )
        
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            stream=False
        )

        async with AsyncWebCrawler() as crawler:
            results = await crawler.arun_many(urls=urls, config=run_config, dispatcher=dispatcher)
            output = []
            for res in results:
                output.append({
                    "url": res.url,
                    "success": res.success,
                    "status_code": res.status_code,
                    "markdown_snippet": (res.markdown.raw_markdown[:300] if hasattr(res.markdown, 'raw_markdown') else str(res.markdown)[:300]) if res.success else None,
                    "error": res.error_message
                })
            return output

    async def adaptive_research_tool(
        self,
        start_url: str,
        query: str,
        confidence_threshold: float = 0.8,
        max_pages: int = 15
    ) -> Dict[str, Any]:
        """
        Tool 4: Autonomous research crawler that stops automatically when it gathers 
        sufficient information for a search query.
        """
        adaptive_config = AdaptiveConfig(
            confidence_threshold=confidence_threshold,
            max_pages=max_pages,
            top_k_links=3
        )

        async with AsyncWebCrawler() as crawler:
            adaptive = AdaptiveCrawler(crawler, config=adaptive_config)
            state = await adaptive.digest(start_url=start_url, query=query)
            
            top_content = adaptive.get_relevant_content(top_k=5)
            
            return {
                "query": query,
                "confidence_achieved": adaptive.confidence,
                "pages_crawled_count": len(state.crawled_urls),
                "is_sufficient": adaptive.is_sufficient,
                "relevant_excerpts": [
                    {"url": item["url"], "score": item["score"], "content": item["content"][:500]}
                    for item in top_content
                ]
            }

    async def virtual_scroll_tool(
        self,
        url: str,
        container_selector: str,
        scroll_count: int = 15,
        wait_after_scroll: float = 0.8
    ) -> Dict[str, Any]:
        """
        Tool 5: Handles virtualized rendering (e.g., Twitter feeds or Instagram grids) 
        where off-screen DOM elements are removed during scrolling.
        """
        v_config = VirtualScrollConfig(
            container_selector=container_selector,
            scroll_count=scroll_count,
            scroll_by="container_height",
            wait_after_scroll=wait_after_scroll
        )

        run_config = CrawlerRunConfig(virtual_scroll_config=v_config)

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=run_config)
            return {
                "success": result.success,
                "url": result.url,
                "html_length": len(result.html),
                "markdown": result.markdown.raw_markdown if hasattr(result.markdown, 'raw_markdown') else result.markdown,
                "error": result.error_message
            }

    async def structured_extraction_tool(
        self,
        url: str,
        extraction_type: str,  # "css", "regex", or "llm"
        schema_or_pattern: Any,
        llm_provider: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool 6: Extracts structured JSON data using CSS schemas, Regex rules, or 
        LLM providers.
        """
        if extraction_type == "css":
            strategy = JsonCssExtractionStrategy(schema=schema_or_pattern)
        elif extraction_type == "regex":
            strategy = RegexExtractionStrategy(custom=schema_or_pattern)
        elif extraction_type == "llm":
            llm_config = LLMConfig(
                provider=llm_provider or "openai/gpt-4o-mini",
                api_token=llm_api_key or os.getenv("OPENAI_API_KEY")
            )
            strategy = LLMExtractionStrategy(
                llm_config=llm_config,
                schema=schema_or_pattern,
                instruction=instruction or "Extract structured data according to schema."
            )
        else:
            raise ValueError("Unsupported extraction_type. Choose 'css', 'regex', or 'llm'.")

        run_config = CrawlerRunConfig(extraction_strategy=strategy)

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=run_config)
            return {
                "success": result.success,
                "url": result.url,
                "extracted_data": json.loads(result.extracted_content) if result.extracted_content else None,
                "error": result.error_message
            }

    async def domain_mapping_tool(
        self,
        domain: str,
        sources: str = "sitemap+cc+crt+probe",
        query_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool 7: Maps an entire target domain across subdomains and endpoint discovery 
        using 8 integrated recon sources.
        """
        mapper_config = DomainMapperConfig(
            source=sources,
            extract_head=True,
            query=query_filter,
            soft_404_detection=True
        )

        async with DomainMapper() as mapper:
            discovered_pages = await mapper.scan(domain=domain, config=mapper_config)

        return {
            "domain": domain,
            "total_urls_found": len(discovered_pages),
            "urls": [
                {
                    "url": page["url"],
                    "source": page.get("source"),
                    "title": page.get("head_data", {}).get("title"),
                    "relevance_score": page.get("relevance_score")
                }
                for page in discovered_pages[:50]  # Cap response size for AI context window
            ]
        }