"""
test_mcp.py

Unit and integration tests for MCPManager, mcp.json/mpc.json parsing,
OAuth redirection probing, OAuth token persistence, ToolkitAdapter MCP integration,
and LocalAgent MCP commands.
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from mcp_manager import MCPManager, MCP_AVAILABLE
from toolkit_adapters import ToolkitAdapter
from orchestrator import LocalAgent, AgentCommand


class TestMCPIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        # Sample mpc.json content as requested in prompt
        self.sample_mcp_config = {
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
                        "FIRECRAWL_API_KEY": "test-key-123"
                    }
                }
            }
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_config_loading_mpc_json(self):
        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        manager = MCPManager(project_root=str(self.root))
        servers = manager.get_server_names()

        self.assertIn("reddit", servers)
        self.assertIn("playwright", servers)
        self.assertIn("firecrawl-mcp", servers)
        self.assertEqual(manager.servers_config["firecrawl-mcp"]["env"]["FIRECRAWL_API_KEY"], "test-key-123")

    def test_config_loading_mcp_json(self):
        mcp_path = self.root / "mcp.json"
        with open(mcp_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        manager = MCPManager(project_root=str(self.root))
        servers = manager.get_server_names()

        self.assertIn("reddit", servers)
        self.assertIn("playwright", servers)
        self.assertIn("firecrawl-mcp", servers)

    def test_oauth_probing_interception(self):
        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        manager = MCPManager(project_root=str(self.root))

        # Discover reddit URL metadata directly
        meta = manager.discover_oauth_metadata("https://mcp.mcpbundles.com/bundle/reddit", {})
        self.assertTrue(meta.get("requires_auth"))
        self.assertIn("authorization_endpoint", meta)

    def test_token_persistence_and_auto_injection(self):
        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        manager = MCPManager(project_root=str(self.root))
        manager.set_server_token("reddit", "sample_oauth_access_token_xyz")

        # Verify saved token file exists
        token_file = self.root / ".mcp_tokens.json"
        self.assertTrue(token_file.exists())
        with open(token_file, "r") as f:
            tokens = json.load(f)
        self.assertEqual(tokens["reddit"]["access_token"], "sample_oauth_access_token_xyz")

        # Re-initialize manager and verify Bearer token injection
        new_manager = MCPManager(project_root=str(self.root))
        reddit_cfg = new_manager.servers_config["reddit"]
        self.assertIn("headers", reddit_cfg)
        self.assertEqual(reddit_cfg["headers"]["Authorization"], "Bearer sample_oauth_access_token_xyz")

    def test_get_mcp_auth_status_adapter(self):
        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        adapter = ToolkitAdapter(project_root=str(self.root))
        adapter.mcp_manager.set_server_token("reddit", "tok123")

        status_res = adapter.dispatch("get_mcp_auth_status", {})
        self.assertIn("reddit", status_res)
        self.assertIn("Authenticated 🔑", status_res)

    @patch.object(MCPManager, "list_tools_async")
    @patch.object(MCPManager, "call_tool_async")
    def test_toolkit_adapter_mcp_tools(self, mock_call, mock_list):
        mock_list.return_value = {
            "mcp_reddit_get_posts": {
                "server_name": "reddit",
                "original_name": "get_posts",
                "qualified_name": "mcp_reddit_get_posts",
                "description": "Get reddit posts",
                "inputSchema": {"type": "object"}
            }
        }
        mock_call.return_value = "Mocked MCP Tool Result"

        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        adapter = ToolkitAdapter(project_root=str(self.root))

        # Check list_mcp_tools dispatch
        res = adapter.dispatch("list_mcp_tools", {})
        self.assertIsInstance(res, str)
        self.assertIn("reddit", res)
        self.assertIn("get_posts", res)

        # Check call_mcp_tool dispatch
        res_call = adapter.dispatch("call_mcp_tool", {"server_name": "reddit", "tool_name": "get_posts"})
        self.assertEqual(res_call, "Mocked MCP Tool Result")

        # Check dispatching qualified name directly
        res_qual = adapter.dispatch("mcp_reddit_get_posts", {})
        self.assertEqual(res_qual, "Mocked MCP Tool Result")

    @patch.object(MCPManager, "list_tools_async")
    @patch.object(MCPManager, "call_tool_async")
    def test_local_agent_mcp_commands(self, mock_call, mock_list):
        mock_list.return_value = {
            "mcp_playwright_navigate": {
                "server_name": "playwright",
                "original_name": "navigate",
                "qualified_name": "mcp_playwright_navigate",
                "description": "Navigate to URL",
                "inputSchema": {"type": "object"}
            }
        }
        mock_call.return_value = "Navigated to page"

        mpc_path = self.root / "mpc.json"
        with open(mpc_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_mcp_config, f)

        agent = LocalAgent(project_path=str(self.root))

        res_list = agent.execute(AgentCommand.LIST_MCP_TOOLS)
        self.assertTrue(res_list.success)
        self.assertIn("playwright", res_list.content)

        res_call = agent.execute(AgentCommand.CALL_MCP_TOOL, server_name="playwright", tool_name="navigate", arguments={"url": "https://example.com"})
        self.assertTrue(res_call.success)
        self.assertEqual(res_call.content, "Navigated to page")


if __name__ == "__main__":
    unittest.main()
