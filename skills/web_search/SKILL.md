---
name: web_search
description: Web search and online documentation research guide using Tavily, Serper, and DuckDuckGo.
version: 1.0.0
tags: [search, web, documentation, research]
---

# Web Search Skill

This skill guides the agent on effectively querying the live web, searching software documentation, and extracting web content.

## Best Practices
1. **Query Construction**: Keep search queries keyword-dense and concise.
2. **Provider Selection**:
   - Set `TAVILY_API_KEY` for LLM-optimized direct answers and clean markdown extraction.
   - Set `SERPER_API_KEY` for Google SERP organic results and knowledge panels.
   - Keyless DuckDuckGo search is automatically used as a zero-config fallback.
3. **Fetching Full Pages**: Use `fetch_web_page(url)` when search snippets are insufficient.
