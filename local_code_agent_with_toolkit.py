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

TOOL_CALL_RE = re.compile(r"call:(\w+)\{([^}]+)\}(?:\s*```\w*\s*(\{.*?\})\s*```)?", re.DOTALL)
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
        # Get the value from whichever capture group matched
        value = m.group(2) or m.group(3) or m.group(4)

        # Strip surrounding quotes if present
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

SYSTEM_TEMPLATE = """You are a coding assistant with access to local filesystem tools and a SKILL framework.
Project root: {project_root}

You have access to the following tools. Use them by emitting a tool call
in the exact format below. Emit ONE tool call per message, then wait for the
result. You may call up to {max_tool_calls} tools per response cycle.

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
- call:read_skill_resource{{skill_name: code_review, resource_rel_path: references/checklist.md}}
- call:execute_skill_script{{skill_name: code_review, script_name: scripts/lint.py}}

Tool schemas:
{tool_schemas}

After each tool call, you will see the result. Based on the result:
- If you have enough information, provide your final answer.
- If you need more info, call another tool (but do NOT repeat failed calls).
- Stop calling tools once you have what you need.

General guidance:
- Use explore() first to understand the project structure.
- Use read_file() or read_chunk() to examine code.
- Use search_symbols() to find functions/classes across the project.
- Use list_skills() and get_skill() to discover domain workflows, references, or specialized scripts.
- Edits are queued by default; call apply_pending_edits() to commit them.
- Always list_pending_edits() before applying to review changes.
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
                   max_turns: int = 1, max_tool_calls: int = MAX_TOOL_CALLS_PER_TURN):
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
    tool_call_counter = 0
    final_response = ""

    for turn in range(max_turns):
        ai_msg = llm.invoke(messages)
        reply = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        messages.append(ai_msg)

        calls = parse_tool_calls_from_text(reply)

        if not calls:
            final_response = reply
            break

        remaining = max_tool_calls - total_tool_calls
        calls = calls[:remaining]
        if not calls:
            final_response = reply
            break

        for idx, call in enumerate(calls, start=1):
            tool_call_counter += 1
            tool_call_id = f"tool_call_{tool_call_counter}"
            total_tool_calls += 1

            name = call.get("name")
            args = call.get("arguments", {})

            try:
                result = adapter.dispatch(name, args)
            except Exception as e:
                result = f"ERROR: {type(e).__name__}: {e}"

            tool_call_log.append({
                "turn": turn,
                "call_index": idx,
                "tool_call_id": tool_call_id,
                "tool_name": name,
                "args": args,
                "result": result[:2000],
            })

            tool_result_text = f"[Tool Result: {name}({json.dumps(args)})]\n{result}"

            tool_msg = ToolMessage(
                content=tool_result_text,
                tool_call_id=tool_call_id,
                name=name,
            )
            messages.append(tool_msg)

        if total_tool_calls >= max_tool_calls:
            final_prompt = HumanMessage(content="You have reached the tool call limit. Provide your final response based on all information gathered.")
            messages.append(final_prompt)
            ai_msg = llm.invoke(messages)
            final_response = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
            break

        # Give LLM a chance to continue or conclude
        follow_up = HumanMessage(content="Review the tool results above. If you have enough information, provide your final answer. Otherwise, call more tools as needed.")
        messages.append(follow_up)

    # FINAL FALLBACK: If no final response was produced, make one more LLM call
    if not final_response:
        final_prompt = HumanMessage(content="Please provide your final response based on all the information gathered above.")
        messages.append(final_prompt)
        ai_msg = llm.invoke(messages)
        final_response = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

    return {
        "final_response": final_response,
        "tool_call_log": tool_call_log,
        "total_tool_calls": total_tool_calls,
    }

def workflow(inputs: Dict[str, Any]) -> Dict[str, Any]:
    project_root = inputs.get("project_root")
    user_prompt = inputs.get("input")
    max_turns = inputs.get("max_turns", 1)
    max_tool_calls = inputs.get("max_tool_calls", MAX_TOOL_CALLS_PER_TURN)

    if not project_root or not user_prompt:
        return {"error": "project_root and input are required"}

    adapter = ToolkitAdapter(project_root)
    adapter.editor.auto_apply = inputs.get("auto_apply_edits", False)

    result = run_agent_loop(
        adapter=adapter,
        user_prompt=user_prompt,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
    )
    return result


# Runnable wrapper matching your FeatherlessAI format
if LANGCHAIN_AVAILABLE:
    workflow_runnable = RunnableLambda(workflow)
else:
    workflow_runnable = None
