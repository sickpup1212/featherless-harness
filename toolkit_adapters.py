# local_agent/toolkit_adapters.py
"""
Adapter layer: exposes your original toolkit classes/functions as named
tools the agent loop can dispatch.
"""
import json
import inspect
from typing import Callable, Dict, Any, List
from pathlib import Path
from filesystem import ProjectExplorer
from code_reader import CodeReader, ProjectIndex
from code_editor import CodeEditor
from skill_manager import SkillManager


class ToolkitAdapter:
    """Wraps your toolkit objects and exposes them as tool-callable functions."""

    def __init__(self, project_root: str):
        self.root = Path(project_root).resolve()

        # Original toolkit instances
        self.explorer = ProjectExplorer(self.root)
        self.reader = CodeReader(self.root)
        self.editor = CodeEditor(self.root)
        self.index = ProjectIndex(self.root)
        self.skill_manager = SkillManager(project_root=self.root)

        # Build the index once here
        self.index.build_index()

        # Tool registry: name -> callable(args_dict) -> str
        self.tools: Dict[str, Callable[[Dict[str, Any]], str]] = {}
        self._register()

    # ---------- registration ----------
    def _register(self):
        self.tools["explore"] = self._wrap_explore
        self.tools["read_file"] = self._wrap(self._read_file)
        self.tools["read_chunk"] = self._wrap(self._read_chunk)
        self.tools["list_symbols"] = self._wrap(self._list_symbols)
        self.tools["search_symbols"] = self._wrap(self._search_symbols)
        self.tools["get_file_overview"] = self._wrap(self._get_file_overview)
        self.tools["get_project_index"] = self._wrap(self.index.get_index_summary)
        self.tools["replace_lines"] = self._wrap(self._replace_lines)
        self.tools["insert_after_line"] = self._wrap(self._insert_after_line)
        self.tools["delete_lines"] = self._wrap(self._delete_lines)
        self.tools["create_file"] = self._wrap(self._create_file)
        self.tools["list_pending_edits"] = self._wrap(self.editor.get_pending_edits_summary)
        self.tools["apply_pending_edits"] = self._wrap(self._apply_pending_edits)
        self.tools["undo_edit"] = self._wrap(self.editor.undo_last_edit)
        self.tools["list_skills"] = self._wrap(self._list_skills)
        self.tools["get_skill"] = self._wrap(self._get_skill)
        self.tools["read_skill_resource"] = self._wrap(self._read_skill_resource)
        self.tools["execute_skill_script"] = self._wrap(self._execute_skill_script)
        self.tools["help"] = self._wrap(self._help)

    def _wrap_explore(self, args: Dict[str, Any]) -> str:
        """Special wrapper for explore to handle max_depth correctly."""
        max_depth = args.get("max_depth", 3)
        try:
            max_depth = int(max_depth)
        except (ValueError, TypeError):
            max_depth = 3
        return self.explorer.get_tree_string(max_depth)

    # ---------- internal wrappers ----------
    def _read_file(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        start = args.get("start_line")
        end = args.get("end_line")

        if rel_path in {".", "", ".."}:
            return "ERROR: Please provide a specific file path."

        full_path = (self.root / rel_path).resolve()

        try:
            full_path.relative_to(self.root)
        except ValueError:
            return "ERROR: Path is outside the project root"

        if not full_path.exists():
            return f"ERROR: File not found: {rel_path}"

        if full_path.is_dir():
            return f"ERROR: '{rel_path}' is a directory, not a file."

        return self.reader.read_file(full_path, start, end, include_line_numbers=True)

    def _read_chunk(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        focus = int(args.get("focus_line", 1))
        context = int(args.get("context_lines", 10))

        if rel_path in {".", "", ".."}:
            return "ERROR: Please provide a specific file path."

        full_path = (self.root / rel_path).resolve()

        try:
            full_path.relative_to(self.root)
        except ValueError:
            return "ERROR: Path is outside the project root"

        if not full_path.exists():
            return f"ERROR: File not found: {rel_path}"

        if full_path.is_dir():
            return f"ERROR: '{rel_path}' is a directory, not a file."

        return self.reader.read_with_context(full_path, focus, context)

    def _list_symbols(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        if not rel_path or rel_path in {".", ".."}:
            return "ERROR: Please provide a specific file path."

        full_path = (self.root / rel_path).resolve()
        try:
            full_path.relative_to(self.root)
        except ValueError:
            return "ERROR: Path is outside the project root"

        if not full_path.exists():
            return f"ERROR: File not found: {rel_path}"

        return self.reader.get_file_symbols(full_path)

    def _search_symbols(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip().strip("'\"")
        results = self.index.search_symbols(query)
        results = [r for r in results if r['symbol']['kind'] in ('function', 'class')]
        results = results[:20]
        if not results:
            return f"No functions/classes found matching '{query}'"
        lines = [f"## Search Results ({len(results)} found):"]
        for r in results[:30]:
            lines.append(f"- `{r['file']}`: {r['symbol']['name']} ({r['symbol']['kind']})")
            doc = r['symbol'].get('docstring', '')
            if doc:
                lines.append(f"  📝 {doc[:120].replace(chr(10), ' ')}...")
        return "\n".join(lines)

    def _get_file_overview(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        if rel_path in {".", "", ".."}:
            return "ERROR: Please provide a specific file path, not a directory or empty string."
        full_path = (self.root / rel_path).resolve()
        try:
            full_path.relative_to(self.root)
        except ValueError:
            return "ERROR: Path is outside the project root"
        if not full_path.exists():
            return f"ERROR: Path not found: {rel_path}"
        if full_path.is_dir():
            return f"ERROR: '{rel_path}' is a directory. Please provide a specific file path."
        return self.reader.get_file_overview(full_path)

    def _replace_lines(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        start = int(args["start_line"])
        end = int(args["end_line"])
        new_content = args.get("new_content", "")
        desc = args.get("description", "")

        full_path = (self.root / rel_path).resolve()
        edit = self.editor.replace_lines(full_path, start, end, new_content, desc)
        status = "applied" if self.editor.auto_apply else "pending"
        return json.dumps({
            "status": status,
            "description": desc,
            "file": rel_path,
            "lines": f"{start}-{end}",
            "new_content_length": len(new_content),
        })

    def _insert_after_line(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        after = int(args["after_line"])
        new_content = args.get("new_content", "")
        desc = args.get("description", "")

        full_path = (self.root / rel_path).resolve()
        edit = self.editor.insert_after_line(full_path, after, new_content, desc)
        return json.dumps({
            "status": "applied" if self.editor.auto_apply else "pending",
            "description": desc,
            "file": rel_path,
        })

    def _delete_lines(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        start = int(args["start_line"])
        end = int(args["end_line"])
        desc = args.get("description", "")

        full_path = (self.root / rel_path).resolve()
        edit = self.editor.delete_lines(full_path, start, end, desc)
        return json.dumps({
            "status": "applied" if self.editor.auto_apply else "pending",
            "description": desc,
            "file": rel_path,
            "lines": f"{start}-{end}",
        })

    def _create_file(self, args: Dict[str, Any]) -> str:
        rel_path = str(args.get("rel_path", "")).strip().strip("'\"")
        content = args.get("content", "")
        desc = args.get("description", "")

        full_path = (self.root / rel_path).resolve()
        edit = self.editor.create_file(full_path, content, desc)
        return json.dumps({
            "status": "applied" if self.editor.auto_apply else "pending",
            "description": desc,
            "file": rel_path,
            "content_length": len(content),
        })

    def _apply_pending_edits(self, args: Dict[str, Any]) -> str:
        applied = self.editor.apply_pending_edits(review_changes=not self.editor.auto_apply)
        return json.dumps({
            "applied_count": len(applied),
            "edits": [{"description": e.description, "file": str(e.file_path)} for e in applied],
        })

    # ---------- Skill tools ----------
    def _list_skills(self, args: Dict[str, Any] = None) -> str:
        skills = self.skill_manager.list_skills()
        if not skills:
            return "No skills found."
        lines = ["## Available Skills:"]
        for s in skills:
            lines.append(f"- **{s['name']}** (v{s['version']}): {s['description']}")
            if s['tags']:
                lines.append(f"  Tags: {', '.join(s['tags'])}")
        return "\n".join(lines)

    def _get_skill(self, args: Dict[str, Any]) -> str:
        skill_name = str(args.get("skill_name", "")).strip().strip("'\"")
        if not skill_name:
            return "ERROR: Please provide a skill_name."
        return self.skill_manager.get_skill_overview(skill_name)

    def _read_skill_resource(self, args: Dict[str, Any]) -> str:
        skill_name = str(args.get("skill_name", "")).strip().strip("'\"")
        resource_path = str(args.get("resource_rel_path", "")).strip().strip("'\"")
        if not skill_name or not resource_path:
            return "ERROR: skill_name and resource_rel_path are required."
        return self.skill_manager.read_skill_resource(skill_name, resource_path)

    def _execute_skill_script(self, args: Dict[str, Any]) -> str:
        skill_name = str(args.get("skill_name", "")).strip().strip("'\"")
        script_name = str(args.get("script_name", "")).strip().strip("'\"")
        script_args = args.get("args")
        if isinstance(script_args, str):
            script_args = [script_args]
        if not skill_name or not script_name:
            return "ERROR: skill_name and script_name are required."
        return self.skill_manager.execute_skill_script(skill_name, script_name, script_args)

    def _help(self, args: Dict[str, Any] = None) -> str:
        return """
## Available Tools

### Exploration
- explore(max_depth: int) -> str
- get_project_index() -> str

### Reading
- read_file(rel_path: str, start_line: int?, end_line: int?) -> str
- read_chunk(rel_path: str, focus_line: int, context_lines: int) -> str
- list_symbols(rel_path: str) -> str
- search_symbols(query: str) -> str
- get_file_overview(rel_path: str) -> str

### Editing (queued by default)
- replace_lines(rel_path: str, start_line: int, end_line: int,
                new_content: str, description: str?) -> json
- insert_after_line(rel_path: str, after_line: int, new_content: str,
                    description: str?) -> json
- delete_lines(rel_path: str, start_line: int, end_line: int,
               description: str?) -> json
- create_file(rel_path: str, content: str, description: str?) -> json
- list_pending_edits() -> str
- apply_pending_edits() -> json
- undo_edit() -> str

### Skills Framework
- list_skills() -> str
- get_skill(skill_name: str) -> str
- read_skill_resource(skill_name: str, resource_rel_path: str) -> str
- execute_skill_script(skill_name: str, script_name: str, args: list?) -> str
"""

    # ---------- generic wrapper ----------
    def _wrap(self, fn: Callable) -> Callable[[Dict[str, Any]], str]:
        """Wrap any function so it accepts a single args dict and returns a string."""
        def wrapper(args: Dict[str, Any] = None) -> str:
            if args is None:
                args = {}
            try:
                sig = inspect.signature(fn)
                params = list(sig.parameters.values())

                if len(params) == 0:
                    result = fn()
                elif len(params) == 1 and (params[0].name == "args" or params[0].annotation == Dict[str, Any]):
                    result = fn(args)
                else:
                    converted_args = {}
                    for param in params:
                        pname = param.name
                        if pname in args:
                            val = args[pname]
                            if param.annotation != inspect.Parameter.empty:
                                try:
                                    if param.annotation == int:
                                        val = int(val)
                                    elif param.annotation == float:
                                        val = float(val)
                                    elif param.annotation == bool:
                                        val = val.lower() in ('true', '1', 'yes') if isinstance(val, str) else bool(val)
                                except (ValueError, AttributeError):
                                    pass
                            converted_args[pname] = val
                        elif param.default != inspect.Parameter.empty:
                            converted_args[pname] = param.default
                    result = fn(**converted_args)

                if not isinstance(result, str):
                    return json.dumps(result, default=str)
                return result
            except Exception as e:
                return f"ERROR: {type(e).__name__}: {e}"
        return wrapper

    def dispatch(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Execute a tool by name (used by the agent loop)."""
        if tool_name not in self.tools:
            return f"ERROR: unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
        return self.tools[tool_name](args)

    def get_tool_schemas(self) -> Dict[str, Any]:
        """Return a dict of tool name -> schema (for use in prompts/system)."""
        return {
            "explore": {"max_depth": "int (default 3)"},
            "read_file": {"rel_path": "str", "start_line": "int?", "end_line": "int?"},
            "read_chunk": {"rel_path": "str", "focus_line": "int", "context_lines": "int"},
            "list_symbols": {"rel_path": "str"},
            "search_symbols": {"query": "str"},
            "get_file_overview": {"rel_path": "str"},
            "get_project_index": {},
            "replace_lines": {"rel_path": "str", "start_line": "int", "end_line": "int",
                              "new_content": "str", "description": "str?"},
            "insert_after_line": {"rel_path": "str", "after_line": "int",
                                  "new_content": "str", "description": "str?"},
            "delete_lines": {"rel_path": "str", "start_line": "int", "end_line": "int",
                             "description": "str?"},
            "create_file": {"rel_path": "str", "content": "str", "description": "str?"},
            "list_pending_edits": {},
            "apply_pending_edits": {},
            "undo_edit": {},
            "list_skills": {},
            "get_skill": {"skill_name": "str"},
            "read_skill_resource": {"skill_name": "str", "resource_rel_path": "str"},
            "execute_skill_script": {"skill_name": "str", "script_name": "str", "args": "list?"},
            "help": {},
        }
