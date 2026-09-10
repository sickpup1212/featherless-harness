"""
mcp_manager.py

Manages Model Context Protocol (MCP) server configurations and integrations.
Supports loading mcp.json or mpc.json config files (with fallback search paths),
connecting to stdio and SSE/URL MCP servers, discovering tools, calling tools,
and intercepting/prompting for OAuth authentication flows and custom headers/tokens.
"""

import os
import json
import asyncio
import logging
import urllib.request
import urllib.error
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
    """Manager for MCP servers, OAuth authorization flow interception, and tool dispatch."""

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
            candidates = [
                self.project_root / "mcp.json",
                self.project_root / "mpc.json",
                self.project_root / ".mcp.json",
                self.project_root / ".mpc.json",
                Path("mcp.json").resolve(),
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

    def set_server_headers(self, server_name: str, headers: Dict[str, str]) -> None:
        """Dynamically set or update HTTP headers for a server."""
        if server_name in self.servers_config:
            if "headers" not in self.servers_config[server_name]:
                self.servers_config[server_name]["headers"] = {}
            self.servers_config[server_name]["headers"].update(headers)

    def set_server_token(self, server_name: str, token: str) -> None:
        """Dynamically set a Bearer token for a server."""
        self.set_server_headers(server_name, {"Authorization": f"Bearer {token}"})

    async def list_tools_async(self) -> Dict[str, Any]:
        """Discover tools across all configured MCP servers asynchronously."""
        if not MCP_AVAILABLE:
            return {"error": "mcp library is not installed."}

        discovered_tools = {}
        self.raw_tools_by_server = {}

        for server_name, server_cfg in self.servers_config.items():
            tools, error_msg = await self._list_tools_for_server(server_name, server_cfg)
            self.raw_tools_by_server[server_name] = tools
            if error_msg and not tools:
                logger.warning(f"MCP server '{server_name}': {error_msg}")
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

    async def _list_tools_for_server(self, server_name: str, server_cfg: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """List tools for a single MCP server, intercepting OAuth requirements if unauthenticated."""
        try:
            if "url" in server_cfg or "uri" in server_cfg:
                url = server_cfg.get("url") or server_cfg.get("uri")
                headers = server_cfg.get("headers", {})

                try:
                    async with sse_client(url, headers=headers) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.list_tools()
                            tools = [
                                {
                                    "name": tool.name,
                                    "description": tool.description or "",
                                    "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                                }
                                for tool in result.tools
                            ]
                            return tools, None
                except Exception as sse_err:
                    auth_prompt = self.probe_oauth_flow(server_name, url, headers)
                    if auth_prompt:
                        return [], auth_prompt
                    return [], f"SSE connection failed for server '{server_name}': {sse_err}"

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
                        tools = [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                            }
                            for tool in result.tools
                        ]
                        return tools, None
            else:
                return [], f"MCP server '{server_name}' has unknown configuration type: {server_cfg}"
        except Exception as e:
            return [], f"Error listing tools for MCP server '{server_name}': {e}"

    def probe_oauth_flow(self, server_name: str, url: str, headers: Dict[str, str]) -> Optional[str]:
        """
        Inspect response from URL-based server to detect OAuth / login requirements,
        redirect endpoints, and well-known authorization metadata.
        """
        try:
            req = urllib.request.Request(url, headers=headers or {})
            resp_body = None
            resp_headers = {}
            status_code = None

            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    status_code = resp.status
                    resp_headers = dict(resp.headers)
                    resp_body = resp.read().decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as http_err:
                status_code = http_err.code
                resp_headers = dict(http_err.headers)
                resp_body = http_err.read().decode("utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"HTTP probe for {url} failed: {e}")
                return None

            # Parse JSON body if available
            data = {}
            if resp_body:
                try:
                    data = json.loads(resp_body)
                except Exception:
                    pass

            resource_meta_url = None
            auth_endpoint = None
            auth_servers = []

            # Check RFC 8288 Link header for oauth-protected-resource
            link_hdr = resp_headers.get("link") or resp_headers.get("Link")
            if link_hdr and "rel=\"oauth-protected-resource\"" in link_hdr:
                # e.g., <https://mcp.mcpbundles.com/bundle/reddit/.well-known/oauth-protected-resource>; rel="oauth-protected-resource"
                start = link_hdr.find("<")
                end = link_hdr.find(">")
                if start != -1 and end != -1:
                    resource_meta_url = link_hdr[start + 1:end]

            if not resource_meta_url and isinstance(data, dict):
                resource_meta_url = data.get("resource_metadata")

            # If resource metadata URL is found, fetch it
            if resource_meta_url:
                try:
                    meta_req = urllib.request.Request(resource_meta_url)
                    with urllib.request.urlopen(meta_req, timeout=5) as meta_resp:
                        meta_data = json.loads(meta_resp.read().decode("utf-8", errors="ignore"))
                        auth_servers = meta_data.get("authorization_servers", [])
                except Exception as e:
                    logger.debug(f"Failed fetching resource metadata {resource_meta_url}: {e}")

            # If authorization server URL is found, fetch well-known endpoint
            if auth_servers:
                auth_server_url = auth_servers[0].rstrip("/")
                well_known_auth = f"{auth_server_url}/.well-known/oauth-authorization-server"
                try:
                    auth_req = urllib.request.Request(well_known_auth)
                    with urllib.request.urlopen(auth_req, timeout=5) as auth_resp:
                        auth_data = json.loads(auth_resp.read().decode("utf-8", errors="ignore"))
                        auth_endpoint = auth_data.get("authorization_endpoint")
                except Exception as e:
                    logger.debug(f"Failed fetching auth server metadata {well_known_auth}: {e}")

            # Determine if login or OAuth redirect is required
            requires_auth = (
                status_code in (401, 403) or
                data.get("status") == "ok" and isinstance(data.get("authentication"), dict) and data.get("authentication", {}).get("required") or
                resource_meta_url is not None or
                auth_endpoint is not None
            )

            if requires_auth:
                prompt_lines = [
                    f"🔒 [MCP OAuth Authentication Required for '{server_name}']",
                    f"Server URL: {url}",
                ]
                if auth_endpoint:
                    prompt_lines.append(f"Authorization Endpoint / Redirect URL: {auth_endpoint}")
                if resource_meta_url:
                    prompt_lines.append(f"Resource Metadata: {resource_meta_url}")

                prompt_lines.extend([
                    "\nTo authorize and access tools for this server, please log in or pass an Authorization token.",
                    "In your mcp.json or mpc.json file, add the Authorization header:",
                    f'"{server_name}": {{',
                    f'  "url": "{url}",',
                    '  "headers": {',
                    '    "Authorization": "Bearer <YOUR_OAUTH_ACCESS_TOKEN>"',
                    '  }',
                    '}'
                ])
                return "\n".join(prompt_lines)

        except Exception as e:
            logger.debug(f"Error probing OAuth flow for {server_name}: {e}")

        return None

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
                headers = server_cfg.get("headers", {})
                try:
                    async with sse_client(url, headers=headers) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            res = await session.call_tool(tool_name, arguments=arguments)
                            return self._format_tool_result(res)
                except Exception as sse_err:
                    auth_prompt = self.probe_oauth_flow(server_name, url, headers)
                    if auth_prompt:
                        return auth_prompt
                    return f"ERROR executing tool '{tool_name}' on MCP server '{server_name}': {sse_err}"

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
