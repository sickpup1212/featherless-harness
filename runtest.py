from pathlib import Path
from toolkit_adapters import ToolkitAdapter
from agent_manager import AgentManager
from orchestrator import LocalAgent, AgentCommand

target_path = Path(".").resolve()
adapter = ToolkitAdapter(str(target_path))

print("=== Testing Agent Discovery ===")
am = AgentManager(project_root=target_path)
agents = am.list_agents()
print(f"Discovered agents count: {len(agents)}")
for a in agents:
    print(f"- Name: {a['name']}, Tools: {a['tools']}")
    print(f"  Description: {a['description']}")

print("\n=== Testing ToolkitAdapter list_agents and get_agent ===")
res_list = adapter.dispatch("list_agents", {})
print(res_list)

res_get = adapter.dispatch("get_agent", {"agent_name": "file-manager"})
print("\n--- File Manager Overview ---")
print(res_get)

print("\n=== Testing call_subagent dispatch ===")
res_sub = adapter.dispatch("call_subagent", {
    "agent_name": "file-manager",
    "prompt": "List files in the directory"
})
print("\n--- Subagent Call Result ---")
print(res_sub[:500])

print("\n=== Testing LocalAgent orchestrator commands ===")
loc_agent = LocalAgent(str(target_path))
resp_agents = loc_agent.execute(AgentCommand.LIST_AGENTS)
print("LIST_AGENTS output:")
print(resp_agents.to_text())

resp_get = loc_agent.execute(AgentCommand.GET_AGENT, agent_name="crawl4ai-agent")
print("\nGET_AGENT output:")
print(resp_get.to_text())

print("\nAll tests finished successfully!")
