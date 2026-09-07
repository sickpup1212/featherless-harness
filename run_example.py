from pathlib import Path
from local_code_agent_with_toolkit import workflow_runnable

target_path = Path(r"C:\Users\edub\Documents\FileExplorer")
if not target_path.exists():
    target_path = Path(".").resolve()

PROJECT = str(target_path)

# 1. Explore + search symbols in one turn (uses multiple tool calls)
print("=== Explore + Search ===")
print(workflow_runnable.invoke({
    "project_root": PROJECT,
    "input": """Use explore(max_depth=2) to see the project structure.
Then use search_symbols to find all functions named 'run' or 'execute'.""",
    "max_turns": 3,
    "max_tool_calls": 20,
}))

print("=== File Overview + Get Index ===")
print(workflow_runnable.invoke({
    "project_root": PROJECT,
    "input": "Use get_file_overview(PROJECT) and get_project_index(PROJECT) and include the results for each in your response",
    "max_turns": 3,
    "max_tool_calls": 20,
}))
