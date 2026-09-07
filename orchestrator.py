# local_agent/orchestrator.py
from typing import List, Dict, Optional, Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import json
import subprocess


class AgentCommand(Enum):
    """Commands an agent can execute."""
    EXPLORE_PROJECT = "explore_project"
    READ_FILE = "read_file"
    READ_CHUNK = "read_chunk"
    LIST_SYMBOLS = "list_symbols"
    SEARCH_SYMBOLS = "search_symbols"
    GET_FILE_OVERVIEW = "get_file_overview"
    GET_PROJECT_INDEX = "get_project_index"
    REPLACE_CONTENT = "replace_content"
    INSERT_CONTENT = "insert_content"
    DELETE_CONTENT = "delete_content"
    CREATE_FILE = "create_file"
    GET_PENDING_EDITS = "get_pending_edits"
    APPLY_EDITS = "apply_edits"
    UNDO_EDIT = "undo_edit"
    LIST_SKILLS = "list_skills"
    GET_SKILL = "get_skill"
    READ_SKILL_RESOURCE = "read_skill_resource"
    EXECUTE_SKILL_SCRIPT = "execute_skill_script"
    WEB_SEARCH = "web_search"
    FETCH_WEB_PAGE = "fetch_web_page"
    SEARCH_CODE_DOCS = "search_code_docs"
    RUN_SHELL = "run_shell"
    GET_WORKDIR = "get_workdir"


@dataclass
class AgentResponse:
    """Response from an agent command."""
    command: AgentCommand
    success: bool = False
    content: str = ""
    metadata: Dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_text(self) -> str:
        """Convert response to text format for agent consumption."""
        if not self.success:
            return f"ERROR: {self.error}"

        if self.content:
            return self.content

        return "OK"


class LocalAgent:
    """Agent that can work with local code projects, skills, and web search."""

    def __init__(self, project_path: str,
                 auto_apply_edits: bool = False,
                 max_file_lines: int = 5000):
        self.project_root = Path(project_path).resolve()
        self.auto_apply = auto_apply_edits
        self.max_file_lines = max_file_lines

        # Initialize tools
        from filesystem import ProjectExplorer
        from code_reader import CodeReader, ProjectIndex
        from code_editor import CodeEditor
        from skill_manager import SkillManager
        from web_search import WebSearchManager

        self.explorer = ProjectExplorer(str(self.project_root))
        self.reader = CodeReader(self.project_root)
        self.editor = CodeEditor(self.project_root, auto_apply=self.auto_apply)
        self.index = ProjectIndex(self.project_root)
        self.skill_manager = SkillManager(project_root=self.project_root)
        self.web_search_manager = WebSearchManager()

        # Build initial index
        self.index.build_index()

        # Command history
        self.history: List[AgentResponse] = []

        # Available tools description for the agent
        self.tools = self._get_tools_description()

    def _get_tools_description(self) -> str:
        """Get description of available tools for the agent."""
        return """
## Available Tools

### Exploration
- `explore_project(max_depth=N)` - View project tree structure
- `get_project_index()` - Get indexed symbols summary
- `list_symbols(file_path)` - List all functions/classes in a file
- `search_symbols(query)` - Search for symbols across project

### Reading
- `read_file(file_path, start_line, end_line)` - Read file content
- `read_chunk(file_path, focus_line, context)` - Read with context
- `get_file_overview(file_path)` - Get file summary with symbols

### Editing
- `replace_content(file_path, start_line, end_line, new_content)`
- `insert_content(file_path, after_line, new_content)`
- `delete_content(file_path, start_line, end_line)`
- `create_file(file_path, content)`
- `get_pending_edits()` - Review pending changes
- `apply_edits()` - Apply all pending changes
- `undo_edit()` - Undo last change

### Skills System
- `list_skills()` - Discover available skills
- `get_skill(skill_name)` - View skill instructions and capabilities
- `read_skill_resource(skill_name, resource_rel_path)` - Read reference doc or schema from skill
- `execute_skill_script(skill_name, script_name, args)` - Run script from skill

### Web Search & Content Fetching
- `web_search(query, max_results)` - Search the live web
- `fetch_web_page(url, max_chars)` - Extract readable markdown content from webpage
- `search_code_docs(query, topic)` - Search library/framework documentation

### Miscellaneous
- `run_shell(command)` - Execute shell command
- `get_workdir()` - Get current project working directory

### Notes
- Edits are queued by default; review before applying
- Set auto_apply_edits=True to auto-apply edits
- File paths are relative to project root
"""

    def execute(self, agent_command: AgentCommand, **kwargs) -> AgentResponse:
        """Execute an agent command."""
        response = AgentResponse(command=agent_command)

        try:
            if not self.project_root.exists():
                response.success = False
                response.error = f"Project not found: {self.project_root}"
                return response

            result = self._handle_command(agent_command, kwargs)
            response.success = True
            response.content = result if isinstance(result, str) else ""
            response.metadata = {}

        except Exception as e:
            response.success = False
            response.error = str(e)

        self.history.append(response)
        return response

    def _handle_command(self, command: AgentCommand,
                        kwargs: Dict) -> str:
        """Route command to appropriate handler."""
        handlers = {
            AgentCommand.EXPLORE_PROJECT: self._cmd_explore,
            AgentCommand.READ_FILE: self._cmd_read_file,
            AgentCommand.READ_CHUNK: self._cmd_read_chunk,
            AgentCommand.LIST_SYMBOLS: self._cmd_list_symbols,
            AgentCommand.SEARCH_SYMBOLS: self._cmd_search_symbols,
            AgentCommand.GET_FILE_OVERVIEW: self._cmd_file_overview,
            AgentCommand.GET_PROJECT_INDEX: self._cmd_project_index,
            AgentCommand.REPLACE_CONTENT: self._cmd_replace,
            AgentCommand.INSERT_CONTENT: self._cmd_insert,
            AgentCommand.DELETE_CONTENT: self._cmd_delete,
            AgentCommand.CREATE_FILE: self._cmd_create_file,
            AgentCommand.GET_PENDING_EDITS: self._cmd_pending_edits,
            AgentCommand.APPLY_EDITS: self._cmd_apply_edits,
            AgentCommand.UNDO_EDIT: self._cmd_undo,
            AgentCommand.LIST_SKILLS: self._cmd_list_skills,
            AgentCommand.GET_SKILL: self._cmd_get_skill,
            AgentCommand.READ_SKILL_RESOURCE: self._cmd_read_skill_resource,
            AgentCommand.EXECUTE_SKILL_SCRIPT: self._cmd_execute_skill_script,
            AgentCommand.WEB_SEARCH: self._cmd_web_search,
            AgentCommand.FETCH_WEB_PAGE: self._cmd_fetch_web_page,
            AgentCommand.SEARCH_CODE_DOCS: self._cmd_search_code_docs,
            AgentCommand.RUN_SHELL: self._cmd_run_shell,
            AgentCommand.GET_WORKDIR: self._cmd_workdir,
        }

        handler = handlers.get(command)
        if not handler:
            raise ValueError(f"Unknown command: {command}")

        return handler(kwargs)

    # Command handlers

    def _cmd_explore(self, kwargs: Dict) -> str:
        max_depth = kwargs.get('max_depth', 3)
        return self.explorer.get_tree_string(max_depth)

    def _cmd_read_file(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        start = kwargs.get('start_line')
        end = kwargs.get('end_line')

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        content = self.reader.read_file(file_path, start, end, include_line_numbers=True)

        # Check size
        line_count = content.count('\n')
        if line_count > self.max_file_lines:
            return (content[:self.max_file_lines * 80] +
                    f"\n\n... [truncated: {line_count} total lines, showing first {self.max_file_lines}]")

        return content

    def _cmd_read_chunk(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        focus = kwargs.get('focus_line', 1)
        context = kwargs.get('context_lines', 10)

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        return self.reader.read_with_context(file_path, focus, context)

    def _cmd_list_symbols(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        return self.reader.get_file_symbols(file_path)

    def _cmd_search_symbols(self, kwargs: Dict) -> str:
        query = kwargs.get('query', '')
        results = self.index.search_symbols(query)

        if not results:
            return f"No symbols found matching '{query}'"

        lines = [f"## Search Results for '{query}' ({len(results)} found)"]
        for r in results[:20]:  # Limit results
            lines.append(f"- `{r['file']}`: {r['symbol']['name']} ({r['symbol']['kind']})")

        return "\n".join(lines)

    def _cmd_file_overview(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        return self.reader.get_file_overview(file_path)

    def _cmd_project_index(self, kwargs: Dict) -> str:
        return self.index.get_index_summary()

    def _cmd_replace(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        start = kwargs.get('start_line')
        end = kwargs.get('end_line')
        new_content = kwargs.get('new_content', '')
        desc = kwargs.get('description', '')

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        edit = self.editor.replace_lines(file_path, start, end, new_content, desc)

        if self.auto_apply:
            return f"Applied: {desc}"

        return f"Pending: {desc}\nEdit queued (use apply_edits to apply)"

    def _cmd_insert(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        after = kwargs.get('after_line')
        new_content = kwargs.get('new_content', '')
        desc = kwargs.get('description', '')

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        edit = self.editor.insert_after_line(file_path, after, new_content, desc)

        if self.auto_apply:
            return f"Applied: {desc}"

        return f"Pending: {desc}"

    def _cmd_delete(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        start = kwargs.get('start_line')
        end = kwargs.get('end_line')
        desc = kwargs.get('description', '')

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        edit = self.editor.delete_lines(file_path, start, end, desc)

        if self.auto_apply:
            return f"Applied: {desc}"

        return f"Pending: {desc}"

    def _cmd_create_file(self, kwargs: Dict) -> str:
        file_path = Path(kwargs.get('file_path', ''))
        content = kwargs.get('content', '')
        desc = kwargs.get('description', '')

        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        edit = self.editor.create_file(file_path, content, desc)

        if self.auto_apply:
            return f"Applied: {desc}"

        return f"Pending: {desc}"

    def _cmd_pending_edits(self, kwargs: Dict) -> str:
        return self.editor.get_pending_edits_summary()

    def _cmd_apply_edits(self, kwargs: Dict) -> str:
        applied = self.editor.apply_pending_edits(review_changes=not self.auto_apply)

        if not applied:
            return "No edits applied."

        lines = [f"Applied {len(applied)} edit(s):"]
        for edit in applied:
            lines.append(f"- {edit.description} ({edit.file_path.name})")

        return "\n".join(lines)

    def _cmd_undo(self, kwargs: Dict) -> str:
        if self.editor.undo_last_edit():
            return "Undid last edit."
        return "No edits to undo."

    def _cmd_list_skills(self, kwargs: Dict) -> str:
        skills = self.skill_manager.list_skills()
        if not skills:
            return "No skills found."
        lines = ["## Available Skills:"]
        for s in skills:
            lines.append(f"- **{s['name']}** (v{s['version']}): {s['description']}")
        return "\n".join(lines)

    def _cmd_get_skill(self, kwargs: Dict) -> str:
        skill_name = kwargs.get("skill_name", "")
        return self.skill_manager.get_skill_overview(skill_name)

    def _cmd_read_skill_resource(self, kwargs: Dict) -> str:
        skill_name = kwargs.get("skill_name", "")
        res_path = kwargs.get("resource_rel_path", "")
        return self.skill_manager.read_skill_resource(skill_name, res_path)

    def _cmd_execute_skill_script(self, kwargs: Dict) -> str:
        skill_name = kwargs.get("skill_name", "")
        script_name = kwargs.get("script_name", "")
        args = kwargs.get("args")
        if isinstance(args, str):
            args = [args]
        return self.skill_manager.execute_skill_script(skill_name, script_name, args)

    def _cmd_web_search(self, kwargs: Dict) -> str:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)
        return self.web_search_manager.search(query, max_results=max_results)

    def _cmd_fetch_web_page(self, kwargs: Dict) -> str:
        url = kwargs.get("url", "")
        max_chars = kwargs.get("max_chars", 4000)
        return self.web_search_manager.fetch_page(url, max_chars=max_chars)

    def _cmd_search_code_docs(self, kwargs: Dict) -> str:
        query = kwargs.get("query", "")
        topic = kwargs.get("topic", "python")
        return self.web_search_manager.search_code_docs(query, topic=topic)

    def _cmd_workdir(self, kwargs: Dict) -> str:
        return str(self.project_root)

    def _cmd_run_shell(self, kwargs: Dict) -> str:
        cmd = kwargs.get('command', '')
        if not cmd:
            return "ERROR: No command provided"
        try:
            res = subprocess.run(cmd, shell=True, cwd=self.project_root, capture_output=True, text=True, timeout=60)
            out = res.stdout
            if res.stderr:
                out += f"\nSTDERR:\n{res.stderr}"
            return out
        except Exception as e:
            return f"ERROR executing shell command: {e}"

    def get_context_summary(self) -> str:
        """Get a summary of the current project state for the agent."""
        tree = self.explorer.get_tree_string(max_depth=2)
        index = self.index.get_index_summary()

        return f"""
## Current Project State

### Project Root
{self.project_root}

### Tree Structure
{tree}

### Index Summary
{index}

{self.tools}
"""
