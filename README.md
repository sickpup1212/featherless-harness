# featherless-harness

A comprehensive harness and local code agent toolkit for Featherless AI models.

## Overview

`featherless-harness` provides a set of tools for local code exploration, AST symbol analysis, line-level code editing, agent orchestration, an extensible **SKILL system**, an LLM-optimized **Web Search framework**, **Crawl4AI Asynchronous Web Crawling**, **MCP Server Support**, and an **Autonomous Agent Execution Loop** (similar to Claude Code or Hermes).

---

## MCP Server Support (`mcp_manager.py`)

The framework supports connecting to external MCP (Model Context Protocol) servers using configuration files formatted as `mcp.json` or `mpc.json`.

### MCP Config Format (`mcp.json` / `mpc.json`)
```json
{
  "mcpServers": {
    "reddit": {
      "url": "https://mcp.mcpbundles.com/bundle/reddit"
    },
    "playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest"
      ]
    },
    "firecrawl-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "firecrawl-mcp"
      ],
      "env": {
        "FIRECRAWL_API_KEY": ""
      }
    }
  }
}
```

### Features
- **Automatic Configuration Loading**: Automatically searches for `mcp.json` or `mpc.json` in project directory or accepts custom path.
- **Stdio and SSE/URL Transports**: Connects to stdio process servers (`npx`, `python`, etc.) and SSE web endpoints.
- **Dynamic Tool Discovery**: `list_mcp_tools()` discovers available tools from all configured MCP servers.
- **Seamless Execution**: `call_mcp_tool(server_name, tool_name, arguments)` dispatches calls to target MCP servers.

---

## Crawl4AI & Asynchronous Web Crawling (`crawl4ai_toolkit.py`)

The framework integrates Crawl4AI for high-performance, asynchronous web crawling and markdown extraction with full async support across `ToolkitAdapter` and `LocalAgent`.

### Features
- **`crawl_url`**: Asynchronously crawls a webpage and extracts clean Markdown (using `crawl4ai` when installed, with an automatic async fallback).
- **`deep_crawl`**: Asynchronously crawls an entire domain up to `max_pages` and `max_depth`.
- **`extract_structured_data`**: Extracts structured text and schema targets from webpages.

---

## Autonomous Agent Execution (Claude Code / Hermes Style)

The framework supports autonomous, multi-turn, multi-tool execution loops (`run_agent_loop`).

### How It Works
1. **High-Level User Prompt**: You give the agent a single, complex prompt (e.g. *"Inspect the codebase for functions without docstrings, write docstrings for them, and run linter"*).
2. **Autonomous Loop (`while not done`)**:
   - The model evaluates current conversation history and emits one or more tool calls.
   - The harness intercepts and dispatches tool calls locally, capturing output into `ToolMessage`s.
   - The harness feeds results directly back into the conversation history and loops automatically until the LLM concludes the task or reaches `max_turns`.
3. **Completion**: When the LLM decides no further tool calls are required, it provides a final summary and breaks out of the loop.

Run the autonomous agent example via:
```bash
python3 run_autonomous_agent.py
```

---

## Web Search Framework & Recommended APIs

Frontier AI web search relies on specialized search APIs optimized for LLMs and RAG rather than raw search engine scraping. `featherless-harness` supports top industry web search providers with automatic keyless fallback:

### Recommended API Providers

| Provider | Environment Variable | Key Benefits & Features |
|---|---|---|
| **Tavily AI** *(Top Choice)* | `TAVILY_API_KEY` | Built specifically for LLM Agents/RAG. Cleans HTML, extracts markdown, eliminates cookie banners/junk, and returns direct AI answers in one call. Get a key at [tavily.com](https://tavily.com). |
| **Serper.dev** | `SERPER_API_KEY` | Fast, reliable Google Search SERP API (~200ms latency). Returns knowledge graphs, answer boxes, and organic results. Get a key at [serper.dev](https://serper.dev). |
| **Brave Search** | `BRAVE_API_KEY` | Fast, independent, privacy-focused search index with rich snippets. Get a key at [brave.com/search/api](https://brave.com/search/api/). |
| **Multi-Layer Keyless Fallback** | *(None required)* | Automatic zero-config fallback combining DuckDuckGo HTML, DuckDuckGo Instant Answer API, and Wikipedia Search API. |

---

## Skills System

The SKILL framework allows agents to utilize domain-specific skills, reference documentation, format specifications, and utility scripts contained within structured skill directories.

### Directory Structure of a Skill

Skills are located in `./skills/<skill_name>/` or `~/.featherless/skills/<skill_name>/`.

```
skills/
├── code_review/
│   ├── SKILL.md                 # Metadata, frontmatter & markdown instructions
│   ├── references/             # Format specs, checklists, schemas & docs
│   │   └── checklist.md
│   └── scripts/                # Executable utility scripts (Python/Bash)
│       └── analyze_quality.py
└── web_search/
    ├── SKILL.md                 # Web search research guidelines
    ├── references/             # Search API provider guide
    │   └── providers_guide.md
    └── scripts/                # Utility scripts
        └── search_and_summarize.py
```

---

## Toolkit & Tools

The framework exposes the following tools via `ToolkitAdapter` and `LocalAgent`:

### Exploration & Reading
- `explore(max_depth: int)`: View project directory tree structure.
- `read_file(rel_path: str, start_line: int?, end_line: int?)`: Read file contents with line numbers.
- `read_chunk(rel_path: str, focus_line: int, context_lines: int)`: Read file with line context.
- `list_symbols(rel_path: str)`: List functions and classes in a file.
- `search_symbols(query: str)`: Search for symbols across the project index.
- `get_file_overview(rel_path: str)`: Get language, size, symbols, and preview.
- `get_project_index()`: Summarize project-wide index.

### Editing
- `replace_lines(rel_path: str, start_line: int, end_line: int, new_content: str, description: str?)`: Queue or apply line replacements.
- `insert_after_line(rel_path: str, after_line: int, new_content: str, description: str?)`: Insert new content.
- `delete_lines(rel_path: str, start_line: int, end_line: int, description: str?)`: Delete line range.
- `create_file(rel_path: str, content: str, description: str?)`: Create a new file.
- `list_pending_edits()`: Review queued edits.
- `apply_pending_edits()`: Apply all pending edits.
- `undo_edit()`: Undo the last edit operation.

### Skills Framework
- `list_skills()`: Discover available skills.
- `get_skill(skill_name: str)`: Get skill instructions, resources, and available scripts.
- `read_skill_resource(skill_name: str, resource_rel_path: str)`: Read reference docs or schemas from a skill.
- `execute_skill_script(skill_name: str, script_name: str, args: list?)`: Execute a utility script from a skill directory.

### Web Search & Async Crawling
- `web_search(query: str, max_results: int?)`: Live web search.
- `fetch_web_page(url: str, max_chars: int?)`: Extract readable page content.
- `search_code_docs(query: str, topic: str?)`: Targeted documentation search.
- `crawl_url(url: str, word_count_threshold: int?, max_chars: int?)`: Async Crawl4AI web crawl.
- `deep_crawl(start_url: str, max_pages: int?, max_depth: int?)`: Async domain crawler.
- `extract_structured_data(url: str, schema_description: str?)`: Extract structured text and schemas.

### MCP Integration
- `list_mcp_tools()`: Discover available tools across configured MCP servers.
- `call_mcp_tool(server_name: str, tool_name: str, arguments: dict?)`: Execute an MCP tool.

---

## Example Usage

```python
from toolkit_adapters import ToolkitAdapter

adapter = ToolkitAdapter(".")

# 1. Discover tools from mcp.json / mpc.json
print(adapter.dispatch("list_mcp_tools", {}))

# 2. Asynchronously crawl a webpage using Crawl4AI
print(adapter.dispatch("crawl_url", {"url": "https://www.python.org", "max_chars": 500}))

# 3. Live web search
print(adapter.dispatch("web_search", {"query": "Python 3.12 release features"}))
```
