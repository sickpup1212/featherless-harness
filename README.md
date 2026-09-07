# featherless-harness

A comprehensive harness and local code agent toolkit for Featherless AI models.

## Overview

`featherless-harness` provides a set of tools for local code exploration, AST symbol analysis, line-level code editing, agent orchestration, and an extensible **SKILL system**.

---

## Skills System

The SKILL framework allows agents to utilize domain-specific skills, reference documentation, format specifications, and utility scripts contained within structured skill directories.

### Directory Structure of a Skill

Skills are located in `./skills/<skill_name>/` or `~/.featherless/skills/<skill_name>/`.

```
skills/
└── code_review/
    ├── SKILL.md                 # Metadata, frontmatter & markdown instructions
    ├── references/             # Format specs, checklists, schemas & docs
    │   └── checklist.md
    └── scripts/                # Executable utility scripts (Python/Bash)
        └── analyze_quality.py
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

## Toolkit & Skill Tools

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

---

## Example Usage

```python
from toolkit_adapters import ToolkitAdapter

adapter = ToolkitAdapter(".")

# Discover available skills
print(adapter.dispatch("list_skills", {}))

# Inspect a skill overview
print(adapter.dispatch("get_skill", {"skill_name": "code_review"}))

# Read reference documentation from a skill
print(adapter.dispatch("read_skill_resource", {
    "skill_name": "code_review",
    "resource_rel_path": "references/checklist.md"
}))

# Run an automated script from a skill
print(adapter.dispatch("execute_skill_script", {
    "skill_name": "code_review",
    "script_name": "scripts/analyze_quality.py"
}))
```
