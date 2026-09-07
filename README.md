# featherless-harness

A comprehensive harness and local code agent toolkit for Featherless AI models.

## Overview

`featherless-harness` provides a set of tools for local code exploration, AST symbol analysis, line-level code editing, agent orchestration, an extensible **SKILL system**, and an LLM-optimized **Web Search framework**.

---

## Web Search Framework & Recommended APIs

Frontier AI web search relies on specialized search APIs optimized for LLMs and RAG rather than raw search engine scraping. `featherless-harness` supports the top industry web search providers with automatic keyless fallback:

### Recommended API Providers

| Provider | Environment Variable | Key Benefits & Features |
|---|---|---|
| **Tavily AI** *(Top Choice)* | `TAVILY_API_KEY` | Built specifically for LLM Agents/RAG. Cleans HTML, extracts markdown, eliminates cookie banners/junk, and returns direct AI answers in one call. Get a key at [tavily.com](https://tavily.com). |
| **Serper.dev** | `SERPER_API_KEY` | Fast, reliable Google Search SERP API (~200ms latency). Returns knowledge graphs, answer boxes, and organic results. Get a key at [serper.dev](https://serper.dev). |
| **Brave Search** | `BRAVE_API_KEY` | Fast, independent, privacy-focused search index with rich snippets. Get a key at [brave.com/search/api](https://brave.com/search/api/). |
| **Multi-Layer Keyless Fallback** | *(None required)* | Automatic zero-config fallback combining DuckDuckGo HTML, DuckDuckGo Instant Answer API, and Wikipedia Search API. |

### Web Search Tools

- `web_search(query: str, max_results: int?)`: Search the live web using Tavily -> Serper -> Brave -> Keyless Fallback.
- `fetch_web_page(url: str, max_chars: int?)`: Extract clean, readable Markdown from any webpage URL with automatic gzip decompression.
- `search_code_docs(query: str, topic: str?)`: Execute targeted documentation searches for software libraries and frameworks.

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

### `SKILL.md` Format

A `SKILL.md` file uses YAML frontmatter followed by markdown instructions:

```markdown
---
name: code_review
description: Comprehensive code review checklist and automated linter helper.
version: 1.1.0
tags: [review, quality, linting]
---

# Code Review Skill

This skill provides guidelines and automated tools for conducting code reviews.

## When to Use
- Before submitting pull requests or committing major changes.

## Capabilities
- Read the checklist reference doc at `references/checklist.md`.
- Run automated code analysis using `scripts/analyze_quality.py`.
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

### Web Search
- `web_search(query: str, max_results: int?)`: Live web search.
- `fetch_web_page(url: str, max_chars: int?)`: Extract readable page content.
- `search_code_docs(query: str, topic: str?)`: Targeted documentation search.

---

## Example Usage

```python
from toolkit_adapters import ToolkitAdapter

adapter = ToolkitAdapter(".")

# 1. Search the live web
print(adapter.dispatch("web_search", {"query": "Python 3.12 release features"}))

# 2. Extract content from a web page
print(adapter.dispatch("fetch_web_page", {"url": "https://docs.python.org/3/whatsnew/3.12.html"}))

# 3. Discover available skills
print(adapter.dispatch("list_skills", {}))

# 4. Inspect a skill overview
print(adapter.dispatch("get_skill", {"skill_name": "web_search"}))

# 5. Read reference documentation from a skill
print(adapter.dispatch("read_skill_resource", {
    "skill_name": "web_search",
    "resource_rel_path": "references/providers_guide.md"
}))

# 6. Run an automated script from a skill
print(adapter.dispatch("execute_skill_script", {
    "skill_name": "web_search",
    "script_name": "scripts/search_and_summarize.py",
    "args": ["FastAPI tutorial"]
}))
```
