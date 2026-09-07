# local_age/local_code_agent_with_toolkit.py
import os
import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import ToolMessage, AIMessage, HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

from toolkit_adapters import ToolkitAdapter

if LANGCHAIN_AVAILABLE:
    FEATHERLESS_API_KEY = os.getenv("FEATHERLESSAI_API_KEY", "")
    llm = ChatOpenAI(
        api_key=FEATHERLESS_API_KEY,
        base_url="https://api.featherless.ai/v1",
        model="TrevorJS/gemma-4-26B-A4B-it-uncensored",
    )

TOOL_CALL_RE = re.compile(r"call:(\w+)\{([^}]*)\}(?:\s*```\w*\s*(\{.*?\})\s*```)?", re.DOTALL)
MAX_TOOL_CALLS_PER_TURN = 20

def parse_tool_calls_from_text(text: str) -> List[Dict[str, Any]]:
    calls = []
    for m in TOOL_CALL_RE.finditer(text):
        tool_name = m.group(1)
        args_str = m.group(2).strip()
        json_str = m.group(3)
        args = {}
        if json_str:
            try:
                payload = json.loads(json_str)
                args = payload.get("arguments", {})
                # Strip quotes from all string values
                args = {k: v.strip().strip("'\"") if isinstance(v, str) else v
                        for k, v in args.items()}
            except json.JSONDecodeError:
                args = parse_inline_args(args_str)
        else:
            args = parse_inline_args(args_str)
        calls.append({"name": tool_name, "arguments": args})
    return calls

def parse_inline_args(args_str: str) -> Dict[str, Any]:
    args = {}
    pattern = r"(\w+)\s*:\s*(?:\"([^\"]+)\"|'([^']+)'|([^,}\s]+))"
    for m in re.finditer(pattern, args_str):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4)
        value = value.strip().strip("'\"")

        if value.isdigit():
            value = int(value)
        else:
            try:
                value = float(value)
            except ValueError:
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
        args[key] = value
    return args

SYSTEM_TEMPLATE = """You are an autonomous coding agent with local filesystem tools, a SKILL framework, and web search capabilities.
Project root: {project_root}

You operate in an autonomous execution loop (similar to Claude Code / Hermes). Given a goal:
1. Break down the task into required steps.
2. Emit tool calls to inspect code, search symbols, read files, run lints/scripts, or search web docs.
3. Observe tool results and continue calling tools until the entire goal is completed.
4. When finished, summarize your work and provide a final answer without emitting any further tool calls.

Tool call format (emit exactly this):
call:tool_name{{argument1: value1, argument2: value2}}

IMPORTANT: Do NOT put quotes around string values unless the value itself contains spaces.

Examples:
- call:explore{{max_depth: 2}}
- call:search_symbols{{query: run}}
- call:read_file{{rel_path: app.py, start_line: 1, end_line: 50}}
- call:get_file_overview{{rel_path: app.py}}
- call:get_project_index{{}}
- call:list_skills{{}}
- call:get_skill{{skill_name: code_review}}
- call:web_search{{query: python asyncio tutorial, max_results: 5}}
- call:fetch_web_page{{url: https://docs.python.org/3/library/asyncio.html}}
- call:search_code_docs{{query: create_task, topic: python}}

Tool schemas:
{tool_schemas}
"""

def build_system(project_root: str, max_tool_calls: int, adapter: ToolkitAdapter) -> str:
    schemas = adapter.get_tool_schemas()
    schema_lines = []
    for name, params in schemas.items():
        param_str = ", ".join(f"{k}: {v}" for k, v in params.items())
        schema_lines.append(f"- {name}({param_str}) -> {('json' if name in {'list_pending_edits','apply_pending_edits','search_symbols','list_symbols'} else 'str')}")
    return SYSTEM_TEMPLATE.format(
        project_root=project_root,
        max_tool_calls=max_tool_calls,
        tool_schemas="\n".join(schema_lines),
    )

def run_agent_loop(adapter: ToolkitAdapter, user_prompt: str,
                   max_turns: int = 15, max_tool_calls: int = 30, verbose: bool = False):
    """Autonomous tool calling loop (Claude Code / Hermes style)."""
    if not LANGCHAIN_AVAILABLE:
        raise RuntimeError("LangChain is required for run_agent_loop")

    project_root = adapter.root
    system = build_system(project_root, max_tool_calls, adapter)

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ]

    tool_call_log: List[Dict[str, Any]] = []
    total_tool_calls = 0
    turn = 0
    final_response = ""

    while turn < max_turns:
        turn += 1
        ai_msg = llm.invoke(messages)
        reply = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        messages.append(ai_msg)

        calls = parse_tool_calls_from_text(reply)

        if not calls:
            final_response = reply
            break

        for idx, call in enumerate(calls, start=1):
            if total_tool_calls >= max_tool_calls:
                break

            total_tool_calls += 1
            tool_name = call.get("name")
            args = call.get("arguments", {})

            try:
                result = adapter.dispatch(tool_name, args)
            except Exception as e:
                result = f"ERROR: {type(e).__name__}: {e}"

            tool_call_log.append({
                "turn": turn,
                "call_index": idx,
                "tool_name": tool_name,
                "args": args,
                "result": result[:2000],
            })

            tool_result_text = f"[Tool Result: {tool_name}({json.dumps(args)})]\n{result}"
            messages.append(ToolMessage(
                content=tool_result_text,
                tool_call_id=f"call_{total_tool_calls}",
                name=tool_name,
            ))

        if total_tool_calls >= max_tool_calls:
            final_prompt = HumanMessage(content="You have reached the tool call limit. Provide your final response based on all information gathered.")
            messages.append(final_prompt)
            ai_msg = llm.invoke(messages)
            final_response = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
            break

    if not final_response:
        final_prompt = HumanMessage(content="Please provide your final summary and conclusion based on all tool execution results.")
        messages.append(final_prompt)
        ai_msg = llm.invoke(messages)
        final_response = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

    return {
        "final_response": final_response,
        "turns_used": turn,
        "total_tool_calls": total_tool_calls,
        "tool_call_log": tool_call_log,
    }

def workflow(inputs: Dict[str, Any]) -> Dict[str, Any]:
    project_root = inputs.get("project_root")
    user_prompt = inputs.get("input")
    max_turns = inputs.get("max_turns", 15)
    max_tool_calls = inputs.get("max_tool_calls", 30)

    if not project_root or not user_prompt:
        return {"error": "project_root and input are required"}

    adapter = ToolkitAdapter(project_root)
    adapter.editor.auto_apply = inputs.get("auto_apply_edits", True)

    result = run_agent_loop(
        adapter=adapter,
        user_prompt=user_prompt,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
    )
    return result


if LANGCHAIN_AVAILABLE:
    workflow_runnable = RunnableLambda(workflow)
else:
    workflow_runnable = None
