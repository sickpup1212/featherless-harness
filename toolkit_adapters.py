# local_agent/toolkit_adapters.py
"""
Adapter layer: exposes your original toolkit classes/functions as named
tools the agent loop can dispatch, with full support for async tools.
"""
import json
import inspect
import asyncio
import concurrent.futures
from typing import Callable, Dict, Any, List, Optional
from pathlib import Path
from filesystem import ProjectExplorer
from code_reader import CodeReader, ProjectIndex
from code_editor import CodeEditor
from skill_manager import SkillManager
from web_search import WebSearchManager
from crawl4ai_toolkit import Crawl4AIToolkit
from agent_manager import AgentManager


def run_async_safely(coro):
    """Run an async coroutine safely from sync code even if an event loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


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
        self.agent_manager = AgentManager(project_root=self.root)
        self.web_search_manager = WebSearchManager()
        self.crawl_toolkit = Crawl4AIToolkit()

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
        self.tools["list_agents"] = self._wrap(self._list_agents)
        self.tools["get_agent"] = self._wrap(self._get_agent)
        self.tools["call_subagent"] = self._wrap(self._call_subagent)
        self.tools["web_search"] = self._wrap(self._web_search)
        self.tools["fetch_web_page"] = self._wrap(self._fetch_web_page)
        self.tools["search_code_docs"] = self._wrap(self._search_code_docs)
        self.tools["crawl_url"] = self._wrap(self.crawl_toolkit.crawl_url)
        self.tools["deep_crawl"] = self._wrap(self.crawl_toolkit.deep_crawl)
        self.tools["extract_structured_data"] = self._wrap(self.crawl_toolkit.extract_structured_data)
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

    # ---------- Agent profile & Subagent tools ----------
    def _list_agents(self, args: Dict[str, Any] = None) -> str:
        agents = self.agent_manager.list_agents()
        if not agents:
            return "No agent profiles found."
        lines = ["## Available Agent Profiles:"]
        for a in agents:
            tools_str = ", ".join(a['tools']) if a['tools'] else "All / Default"
            lines.append(f"- **{a['name']}**: {a['description']} [Tools: {tools_str}]")
        return "\n".join(lines)

    def _get_agent(self, args: Dict[str, Any]) -> str:
        agent_name = str(args.get("agent_name", "")).strip().strip("'\"")
        if not agent_name:
            return "ERROR: Please provide an agent_name."
        return self.agent_manager.get_agent_overview(agent_name)

    def _call_subagent(self, args: Dict[str, Any]) -> str:
        agent_name = str(args.get("agent_name", "")).strip().strip("'\"")
        prompt = str(args.get("prompt", "")).strip()

        if not agent_name or not prompt:
            return "ERROR: agent_name and prompt are required."

        agent = self.agent_manager.get_agent(agent_name)
        if not agent:
            available = list(self.agent_manager.agents.keys())
            return f"ERROR: Agent '{agent_name}' not found. Available agents: {available}"

        try:
            from local_code_agent_with_toolkit import run_agent_loop, LANGCHAIN_AVAILABLE
            if not LANGCHAIN_AVAILABLE:
                return (
                    f"[Subagent Call Simulation for '{agent_name}']\n"
                    f"Agent Description: {agent.description}\n"
                    f"Allowed Tools: {agent.tools}\n"
                    f"Prompt: {prompt}\n"
                    f"Note: LangChain is not installed, subagent execution simulated."
                )

            res = run_agent_loop(
                adapter=self,
                user_prompt=prompt,
                max_turns=args.get("max_turns", 10),
                max_tool_calls=args.get("max_tool_calls", 20),
                agent_name=agent_name,
            )
            return f"[Subagent '{agent_name}' Result]\n{res.get('final_response', '')}"
        except Exception as e:
            return f"ERROR executing subagent '{agent_name}': {e}"

    # ---------- Web Search tools ----------
    def _web_search(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip().strip("'\"")
        max_results = int(args.get("max_results", 5))
        return self.web_search_manager.search(query, max_results=max_results)

    def _fetch_web_page(self, args: Dict[str, Any]) -> str:
        url = str(args.get("url", "")).strip().strip("'\"")
        max_chars = int(args.get("max_chars", 4000))
        return self.web_search_manager.fetch_page(url, max_chars=max_chars)

    def _search_code_docs(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip().strip("'\"")
        topic = str(args.get("topic", "python")).strip().strip("'\"")
        return self.web_search_manager.search_code_docs(query, topic=topic)

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

### Agent Profiles & Subagents
- list_agents() -> str
- get_agent(agent_name: str) -> str
- call_subagent(agent_name: str, prompt: str) -> str

### Web Search & Async Crawling
- web_search(query: str, max_results: int?) -> str
- fetch_web_page(url: str, max_chars: int?) -> str
- search_code_docs(query: str, topic: str?) -> str
- crawl_url(url: str, word_count_threshold: int?, max_chars: int?) -> str
- deep_crawl(start_url: str, max_pages: int?, max_depth: int?) -> str
- extract_structured_data(url: str, schema_description: str?) -> str
"""

    # ---------- generic wrapper supporting sync and async functions ----------
    def _wrap(self, fn: Callable) -> Callable[[Dict[str, Any]], str]:
        """Wrap any sync or async function so it accepts a single args dict and returns a string."""
        is_async = inspect.iscoroutinefunction(fn)

        def wrapper(args: Dict[str, Any] = None) -> str:
            if args is None:
                args = {}
            try:
                sig = inspect.signature(fn)
                params = list(sig.parameters.values())

                if len(params) == 0:
                    raw_res = fn()
                elif len(params) == 1 and (params[0].name == "args" or params[0].annotation == Dict[str, Any]):
                    raw_res = fn(args)
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
                    raw_res = fn(**converted_args)

                if is_async or inspect.iscoroutine(raw_res):
                    result = run_async_safely(raw_res)
                else:
                    result = raw_res

                if not isinstance(result, str):
                    return json.dumps(result, default=str)
                return result
            except Exception as e:
                return f"ERROR: {type(e).__name__}: {e}"
        return wrapper

    def dispatch(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Execute a tool by name synchronously (used by the agent loop)."""
        if tool_name not in self.tools:
            return f"ERROR: unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
        return self.tools[tool_name](args)

    async def dispatch_async(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Execute a tool by name asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.dispatch, tool_name, args)

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
            "list_agents": {},
            "get_agent": {"agent_name": "str"},
            "call_subagent": {"agent_name": "str", "prompt": "str"},
            "web_search": {"query": "str", "max_results": "int?"},
            "fetch_web_page": {"url": "str", "max_chars": "int?"},
            "search_code_docs": {"query": "str", "topic": "str?"},
            "crawl_url": {"url": "str", "word_count_threshold": "int?", "max_chars": "int?"},
            "deep_crawl": {"start_url": "str", "max_pages": "int?", "max_depth": "int?"},
            "extract_structured_data": {"url": "str", "schema_description": "str?"},
            "help": {},
        }
