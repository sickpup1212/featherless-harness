#!/usr/bin/env python3
"""
run_autonomous_agent.py

Demonstrates autonomous multi-tool execution (Claude Code / Hermes style)
using featherless-harness.
"""
from pathlib import Path
from toolkit_adapters import ToolkitAdapter
from local_code_agent_with_toolkit import run_agent_loop, LANGCHAIN_AVAILABLE

def main():
    target_path = Path(".").resolve()
    print(f"=== Running Autonomous Agent in {target_path} ===")

    adapter = ToolkitAdapter(str(target_path))
    adapter.editor.auto_apply = True

    goal = """Use explore(max_depth=2) to inspect the project structure.
Then use list_skills() to check available skills.
Then search_symbols for 'parse_tool_calls' and summarize what you find."""

    if not LANGCHAIN_AVAILABLE:
        print("LangChain dependencies not installed. Testing local tool dispatch manually:")
        print("\n1. Explore:\n", adapter.dispatch("explore", {"max_depth": 2}))
        print("\n2. Skills:\n", adapter.dispatch("list_skills", {}))
        print("\n3. Search:\n", adapter.dispatch("search_symbols", {"query": "parse_tool_calls"}))
        return

    result = run_agent_loop(
        adapter=adapter,
        user_prompt=goal,
        max_turns=10,
        max_tool_calls=20,
    )

    print("\n=== Agent Result ===")
    print("Turns Used:", result["turns_used"])
    print("Total Tool Calls:", result["total_tool_calls"])
    print("Final Response:\n", result["final_response"])

if __name__ == "__main__":
    main()
