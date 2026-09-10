import json
from pathlib import Path
from toolkit_adapters import ToolkitAdapter
from agent_manager import AgentManager
from orchestrator import LocalAgent, AgentCommand

target_path = Path(".").resolve()

# Create a temporary mpc.json for runtest.py verification
sample_mcp_config = {
    "mcpServers": {
        "reddit": {
            "url": "https://mcp.mcpbundles.com/bundle/reddit"
        },
        "playwright": {
            "command": "npx",
            "args": ["@playwright/mcp@latest"]
        },
        "firecrawl-mcp": {
            "command": "npx",
            "args": ["-y", "firecrawl-mcp"],
            "env": {
                "FIRECRAWL_API_KEY": ""
            }
        }
    }
}
mpc_file = target_path / "mpc.json"
created_mpc = False
if not mpc_file.exists():
    with open(mpc_file, "w", encoding="utf-8") as f:
        json.dump(sample_mcp_config, f, indent=2)
    created_mpc = True

try:
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

    print("\n=== Testing MCP Integration in ToolkitAdapter & LocalAgent ===")
    print("Configured MCP Servers:", adapter.mcp_manager.get_server_names())
    mcp_list_res = adapter.dispatch("list_mcp_tools", {})
    print("\n--- MCP Tools List Output ---")
    print(mcp_list_res[:300])

    print("\n=== Testing LocalAgent orchestrator commands ===")
    loc_agent = LocalAgent(str(target_path))
    resp_agents = loc_agent.execute(AgentCommand.LIST_AGENTS)
    print("LIST_AGENTS output:")
    print(resp_agents.to_text())

    resp_mcp = loc_agent.execute(AgentCommand.LIST_MCP_TOOLS)
    print("\nLIST_MCP_TOOLS output:")
    print(resp_mcp.to_text()[:300])

    resp_get = loc_agent.execute(AgentCommand.GET_AGENT, agent_name="crawl4ai-agent")
    print("\nGET_AGENT output:")
    print(resp_get.to_text())

    print("\nAll tests finished successfully!")

finally:
    if created_mpc and mpc_file.exists():
        mpc_file.unlink()
