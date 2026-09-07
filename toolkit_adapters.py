# local_age/toolkit_adapters.py
"""
Adapter layer: exposes your original toolkit classes/functions as named
tools the agent loop can dispatch. No changes needed to your original code.
"""
import json
from typing import Callable, Dict, Any
from toolkit.filesystem import ProjectExplorer
from toolkit.code_reader import CodeReader, ProjectIndex
from toolkit.code_editor import CodeEditor


class ToolkitAdapter:
    """Wraps your toolkit objects and exposes them as tool-callable functions."""

    def __init__(self, project_root: str):
        from pathlib import Path
        from toolkit.filesystem import ProjectExplorer
        self.root = Path(project_root).resolve()

        # Original toolkit instances (unchanged from your code)
        self.explorer = ProjectExplorer(self.root)
        self.reader = CodeReader(self.root)
        self.editor = CodeEditor(self.root)
        self.index = ProjectIndex(self.root)

        # Build the index once here (or lazy-load per tool call)
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
        self.tools["help"] = self._wrap(self._help)

    def _wrap_explore(self, args: Dict[str, Any]) -> str:
        """Special wrapper for explore to handle max_depth correctly."""
        max_depth = args.get("max_depth", 3)
        try:
            max_depth = int(max_depth)
        except (ValueError, TypeError):
            max_depth = 3
        return self.explorer.get_tree_string(max_depth)

    # ---------- internal wrappers (convert tool args -> toolkit calls) ----------
    def _read_file(self, args: Dict[str, Any]) -> str:
        rel_path = args.get("rel_path", "")
        start = args.get("start_line")
        end = args.get("end_line")
        path = self.root / rel_path if isinstance(self.root, str) else self.root / rel_path
        # CodeReader.read_file expects a Path
        from pathlib import Path
        return self.reader.read_file(Path(rel_path), start, end, include_line_numbers=True)

    def _read_file(self, args: Dict[str, Any]) -> str:
        from pathlib import Path
    
        rel_path = args.get("rel_path", "").strip().strip("'\"")
        start = args.get("start_line")
        end = args.get("end_line")
    
        if rel_path in {".", "", "."}:
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
        from pathlib import Path
    
        rel_path = args.get("rel_path", "").strip().strip("'\"")
        focus = int(args.get("focus_line", 1))
        context = int(args.get("context_lines", 10))
    
        if rel_path in {".", "", "."}:
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
        from pathlib import Path
        rel_path = args.get("rel_path", "")
        return self.reader.get_file_symbols(Path(rel_path))

    def _search_symbols(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "").strip().strip("'\"")  # Strip quotes
        print(f"DEBUG search_symbols: query='{query}'")  # Debug line  
        results = self.index.search_symbols(query)
        print(f"DEBUG: found {len(results)} results")
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
        from pathlib import Path    
        rel_path = args.get("rel_path", "").strip().strip("'\"")    
        # Reject empty or current-directory references
        if rel_path in {".", "", "."}:
            return "ERROR: Please provide a specific file path, not a directory or empty string."    
        # Resolve the full path
        full_path = (self.root / rel_path).resolve()    
        # Security check: ensure it's within project root
        try:
            full_path.relative_to(self.root)
        except ValueError:
            return "ERROR: Path is outside the project root"    
        # Check if path exists
        if not full_path.exists():
            return f"ERROR: Path not found: {rel_path}"    
        # Check if it's a directory (reject directories)
        if full_path.is_dir():
            return f"ERROR: '{rel_path}' is a directory. Please provide a specific file path."    
        # Now it's a valid file — read it
        return self.reader.get_file_overview(full_path)

    def _replace_lines(self, args: Dict[str, Any]) -> str:
        from pathlib import Path
        rel_path = args.get("rel_path", "")
        start = int(args["start_line"])
        end = int(args["end_line"])
        new_content = args.get("new_content", "")
        desc = args.get("description", "")
        # Returns the Edit object; we stringify status
        edit = self.editor.replace_lines(Path(rel_path), start, end, new_content, desc)
        status = "applied" if self.editor.auto_apply else "pending"
        return json.dumps({
            "status": status,
            "description": desc,
            "file": rel_path,
            "lines": f"{start}-{end}",
            "new_content_length": len(new_content),
        })

    def _insert_after_line(self, args: Dict[str, Any]) -> str:
        from pathlib import Path
        rel_path = args.get("rel_path", "")
        after = int(args["after_line"])
        new_content = args.get("new_content", "")
        desc = args.get("description", "")
        edit = self.editor.insert_after_line(Path(rel_path), after, new_content, desc)
        return json.dumps({
            "status": "applied" if self.editor.auto_apply else "pending",
            "description": desc,
            "file": rel_path,
        })

    def _delete_lines(self, args: Dict[str, Any]) -> str:
        from pathlib import Path
        rel_path = args.get("rel_path", "")
        start = int(args["start_line"])
        end = int(args["end_line"])
        desc = args.get("description", "")
        edit = self.editor.delete_lines(Path(rel_path), start, end, desc)
        return json.dumps({
            "status": "applied" if self.editor.auto_apply else "pending",
            "description": desc,
            "file": rel_path,
            "lines": f"{start}-{end}",
        })

    def _create_file(self, args: Dict[str, Any]) -> str:
        from pathlib import Path
        rel_path = args.get("rel_path", "")
        content = args.get("content", "")
        desc = args.get("description", "")
        edit = self.editor.create_file(Path(rel_path), content, desc)
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

    def _help(self, args: Dict[str, Any]) -> str:
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
"""

    # ---------- generic wrapper ----------
    def _wrap(self, fn: Callable) -> Callable[[Dict[str, Any]], str]:
        """Wrap any function so it accepts a single args dict and returns a string."""
        def wrapper(args: Dict[str, Any]) -> str:
            try:
                # Convert string args to appropriate types based on the function signature
                import inspect
                sig = inspect.signature(fn)
                converted_args = {}
                for param_name, param in sig.parameters.items():
                    if param_name in args:
                        value = args[param_name]
                        # Convert to expected type if possible
                        if param.annotation != inspect.Parameter.empty:
                            try:
                                if param.annotation == int:
                                    value = int(value)
                                elif param.annotation == float:
                                    value = float(value)
                                elif param.annotation == bool:
                                    value = value.lower() in ('true', '1', 'yes') if isinstance(value, str) else bool(value)
                            except (ValueError, AttributeError):
                                pass  # Keep original value if conversion fails
                        converted_args[param_name] = value
                    elif param.default != inspect.Parameter.empty:
                        converted_args[param_name] = param.default
            
                result = fn(converted_args)
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
        # You can hand-write these or derive from type hints; here's a minimal set
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
            "help": {},
        }