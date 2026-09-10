"""
mcp_manager.py

Manages Model Context Protocol (MCP) server configurations and integrations.
Supports loading mcp.json or mpc.json config files (with fallback search paths),
connecting to stdio and SSE/URL MCP servers, discovering tools, and calling tools.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import mcp
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPManager:
    """Manager for MCP servers and tool discovery/dispatch."""

    def __init__(self, project_root: Optional[str] = None, config_path: Optional[str] = None):
        self.project_root = Path(project_root).resolve() if project_root else Path.cwd()
        self.config_path = Path(config_path) if config_path else None
        self.servers_config: Dict[str, Any] = {}
        self.tools_cache: Dict[str, Dict[str, Any]] = {}  # qualified_name -> tool info
        self.raw_tools_by_server: Dict[str, List[Dict[str, Any]]] = {}

        self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Find and load mcp.json or mpc.json file."""
        target_file = None

        if self.config_path:
            if self.config_path.is_absolute():
                target_file = self.config_path
            else:
                target_file = self.project_root / self.config_path

        if not target_file or not target_file.exists():
            # Candidates to search in project root and current directory
            candidates = [
                self.project_root / "mcp.json",
                self.project_root / "mpc.json",
                self.project_root / ".mcp.json",
                self.project_root / ".mpc.json",
                Path("mcp.json").resolve(),
                Path("mpc.json").resolve(),
                Path("mpc.json").resolve(),
            ]

            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    target_file = candidate
                    break

        if not target_file or not target_file.exists():
            self.servers_config = {}
            return {}

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "mcpServers" in data and isinstance(data["mcpServers"], dict):
                self.servers_config = data["mcpServers"]
            elif isinstance(data, dict):
                self.servers_config = data
            else:
                self.servers_config = {}

            return self.servers_config
        except Exception as e:
            logger.error(f"Error loading MCP config from {target_file}: {e}")
            self.servers_config = {}
            return {}

    def get_server_names(self) -> List[str]:
        """Return names of all configured MCP servers."""
        return list(self.servers_config.keys())

    async def list_tools_async(self) -> Dict[str, Any]:
        """Discover tools across all configured MCP servers asynchronously."""
        if not MCP_AVAILABLE:
            return {"error": "mcp library is not installed."}

        discovered_tools = {}
        self.raw_tools_by_server = {}

        for server_name, server_cfg in self.servers_config.items():
            tools = await self._list_tools_for_server(server_name, server_cfg)
            self.raw_tools_by_server[server_name] = tools
            for t in tools:
                tool_name = t.get("name")
                qualified_name = f"mcp_{server_name}_{tool_name}"
                tool_info = {
                    "server_name": server_name,
                    "original_name": tool_name,
                    "qualified_name": qualified_name,
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                }
                discovered_tools[qualified_name] = tool_info

        self.tools_cache = discovered_tools
        return discovered_tools

    def list_tools(self) -> Dict[str, Any]:
        """Synchronous wrapper for list_tools_async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, self.list_tools_async()).result()
        else:
            return asyncio.run(self.list_tools_async())

    async def _list_tools_for_server(self, server_name: str, server_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List tools for a single MCP server."""
        try:
            if "url" in server_cfg or "uri" in server_cfg:
                url = server_cfg.get("url") or server_cfg.get("uri")
                async with sse_client(url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                            }
                            for tool in result.tools
                        ]
            elif "command" in server_cfg:
                cmd = server_cfg["command"]
                args = server_cfg.get("args", [])
                env = os.environ.copy()
                if "env" in server_cfg and isinstance(server_cfg["env"], dict):
                    env.update(server_cfg["env"])

                params = StdioServerParameters(command=cmd, args=args, env=env)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                            }
                            for tool in result.tools
                        ]
            else:
                logger.warning(f"MCP server '{server_name}' has unknown configuration type: {server_cfg}")
                return []
        except Exception as e:
            logger.error(f"Error listing tools for MCP server '{server_name}': {e}")
            return []

    async def call_tool_async(self, server_name: str, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """Call a tool on an MCP server asynchronously."""
        if not MCP_AVAILABLE:
            return "ERROR: mcp library is not installed."

        if server_name not in self.servers_config:
            return f"ERROR: MCP server '{server_name}' is not configured."

        server_cfg = self.servers_config[server_name]
        if arguments is None:
            arguments = {}

        try:
            if "url" in server_cfg or "uri" in server_cfg:
                url = server_cfg.get("url") or server_cfg.get("uri")
                async with sse_client(url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        res = await session.call_tool(tool_name, arguments=arguments)
                        return self._format_tool_result(res)
            elif "command" in server_cfg:
                cmd = server_cfg["command"]
                args = server_cfg.get("args", [])
                env = os.environ.copy()
                if "env" in server_cfg and isinstance(server_cfg["env"], dict):
                    env.update(server_cfg["env"])

                params = StdioServerParameters(command=cmd, args=args, env=env)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        res = await session.call_tool(tool_name, arguments=arguments)
                        return self._format_tool_result(res)
            else:
                return f"ERROR: Invalid server config for '{server_name}'"
        except Exception as e:
            return f"ERROR executing tool '{tool_name}' on MCP server '{server_name}': {e}"

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """Synchronous wrapper for call_tool_async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, self.call_tool_async(server_name, tool_name, arguments)).result()
        else:
            return asyncio.run(self.call_tool_async(server_name, tool_name, arguments))

    def _format_tool_result(self, res: Any) -> str:
        """Format the result returned by session.call_tool."""
        parts = []

        if hasattr(res, "content") and isinstance(res.content, list):
            for content_block in res.content:
                if hasattr(content_block, "text"):
                    parts.append(content_block.text)
                elif hasattr(content_block, "data"):
                    parts.append(str(content_block.data))
                else:
                    parts.append(str(content_block))
        elif hasattr(res, "structured_content") and res.structured_content:
            parts.append(json.dumps(res.structured_content, indent=2))
        else:
            parts.append(str(res))

        output = "\n".join(parts)
        if hasattr(res, "is_error") and res.is_error:
            return f"MCP Tool Error:\n{output}"
        return output
