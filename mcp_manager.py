"""
mcp_manager.py

Manages Model Context Protocol (MCP) server configurations and integrations.
Supports loading mcp.json or mpc.json config files (with fallback search paths),
connecting to stdio and SSE/URL MCP servers, discovering tools, calling tools,
and built-in OAuth login flows (browser redirect, PKCE, callback listener, token persistence).
"""

import os
import json
import asyncio
import logging
import urllib.request
import urllib.parse
import urllib.error
import base64
import hashlib
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Dict, Any, List, Optional, Tuple
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


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local HTTP server handler to receive OAuth redirect authorization code."""

    auth_code: Optional[str] = None
    error: Optional[str] = None

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization Successful!</h1><p>You may now close this browser tab and return to featherless-harness.</p>")
        elif "error" in params:
            OAuthCallbackHandler.error = params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            err_msg = params["error"][0]
            self.wfile.write(f"<h1>Authorization Failed</h1><p>{err_msg}</p>".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class MCPManager:
    """Manager for MCP servers, OAuth authentication flows, token persistence, and tool dispatch."""

    def __init__(self, project_root: Optional[str] = None, config_path: Optional[str] = None):
        self.project_root = Path(project_root).resolve() if project_root else Path.cwd()
        self.config_path = Path(config_path) if config_path else None
        self.token_file = self.project_root / ".mcp_tokens.json"

        self.servers_config: Dict[str, Any] = {}
        self.stored_tokens: Dict[str, Dict[str, Any]] = {}
        self.tools_cache: Dict[str, Dict[str, Any]] = {}  # qualified_name -> tool info
        self.raw_tools_by_server: Dict[str, List[Dict[str, Any]]] = {}

        self.load_tokens()
        self.load_config()

    def load_tokens(self) -> Dict[str, Dict[str, Any]]:
        """Load saved OAuth tokens from .mcp_tokens.json."""
        if self.token_file.exists():
            try:
                with open(self.token_file, "r", encoding="utf-8") as f:
                    self.stored_tokens = json.load(f)
            except Exception as e:
                logger.error(f"Error loading stored MCP tokens: {e}")
                self.stored_tokens = {}
        else:
            self.stored_tokens = {}
        return self.stored_tokens

    def save_tokens(self) -> None:
        """Save OAuth tokens to .mcp_tokens.json securely."""
        try:
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(self.stored_tokens, f, indent=2)
            os.chmod(self.token_file, 0o600)  # Restrict permissions
        except Exception as e:
            logger.error(f"Error saving MCP tokens: {e}")

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

            # Inject stored bearer tokens if available
            for server_name, server_cfg in self.servers_config.items():
                if server_name in self.stored_tokens and "access_token" in self.stored_tokens[server_name]:
                    token = self.stored_tokens[server_name]["access_token"]
                    if "headers" not in server_cfg:
                        server_cfg["headers"] = {}
                    server_cfg["headers"]["Authorization"] = f"Bearer {token}"

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
        """Dynamically set a Bearer token for a server and save it."""
        self.stored_tokens[server_name] = {"access_token": token}
        self.save_tokens()
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

    async def _list_tools_for_server(self, server_name: str, server_cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
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
                    auth_info = self.discover_oauth_metadata(url, headers)
                    if auth_info and auth_info.get("requires_auth"):
                        prompt = (
                            f"🔒 [MCP OAuth Authentication Required for '{server_name}']\n"
                            f"Server URL: {url}\n"
                            f"Authorization Endpoint: {auth_info.get('authorization_endpoint')}\n"
                            f"Use tool call `authenticate_mcp_server(server_name='{server_name}')` to perform OAuth login."
                        )
                        return [], prompt
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

    def discover_oauth_metadata(self, url: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
        """Discover OAuth metadata endpoints, client registration, and auth URLs."""
        res = {
            "requires_auth": False,
            "resource_metadata_url": None,
            "authorization_endpoint": None,
            "token_endpoint": None,
            "registration_endpoint": None,
            "authorization_servers": [],
            "client_id": None,
        }

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
                return res

            data = {}
            if resp_body:
                try:
                    data = json.loads(resp_body)
                except Exception:
                    pass

            link_hdr = resp_headers.get("link") or resp_headers.get("Link")
            if link_hdr and "rel=\"oauth-protected-resource\"" in link_hdr:
                start = link_hdr.find("<")
                end = link_hdr.find(">")
                if start != -1 and end != -1:
                    res["resource_metadata_url"] = link_hdr[start + 1:end]

            if not res["resource_metadata_url"] and isinstance(data, dict):
                res["resource_metadata_url"] = data.get("resource_metadata")

            if res["resource_metadata_url"]:
                try:
                    meta_req = urllib.request.Request(res["resource_metadata_url"])
                    with urllib.request.urlopen(meta_req, timeout=5) as meta_resp:
                        meta_data = json.loads(meta_resp.read().decode("utf-8", errors="ignore"))
                        res["authorization_servers"] = meta_data.get("authorization_servers", [])
                except Exception as e:
                    logger.debug(f"Failed fetching resource metadata {res['resource_metadata_url']}: {e}")

            if res["authorization_servers"]:
                auth_server_url = res["authorization_servers"][0].rstrip("/")
                well_known_auth = f"{auth_server_url}/.well-known/oauth-authorization-server"
                try:
                    auth_req = urllib.request.Request(well_known_auth)
                    with urllib.request.urlopen(auth_req, timeout=5) as auth_resp:
                        auth_data = json.loads(auth_resp.read().decode("utf-8", errors="ignore"))
                        res["authorization_endpoint"] = auth_data.get("authorization_endpoint")
                        res["token_endpoint"] = auth_data.get("token_endpoint")
                        res["registration_endpoint"] = auth_data.get("registration_endpoint")
                except Exception as e:
                    logger.debug(f"Failed fetching auth server metadata {well_known_auth}: {e}")

            res["requires_auth"] = (
                status_code in (401, 403) or
                data.get("status") == "ok" and isinstance(data.get("authentication"), dict) and data.get("authentication", {}).get("required") or
                res["resource_metadata_url"] is not None or
                res["authorization_endpoint"] is not None
            )

        except Exception as e:
            logger.debug(f"Error in discover_oauth_metadata for {url}: {e}")

        return res

    def authenticate_server_oauth(self, server_name: str, port: int = 8089, timeout_seconds: int = 120) -> str:
        """
        Intercepts and handles full OAuth authentication flow:
        1. Probes server for OAuth endpoints.
        2. Generates PKCE verifier & challenge.
        3. Registers OAuth client dynamically if registration endpoint exists.
        4. Launches local HTTP server callback listener.
        5. Opens browser redirect to login/authorization page.
        6. Receives auth code, exchanges for access token, securely persists token, and updates server headers.
        """
        if server_name not in self.servers_config:
            return f"ERROR: Server '{server_name}' is not configured in mcp.json/mpc.json."

        server_cfg = self.servers_config[server_name]
        url = server_cfg.get("url") or server_cfg.get("uri")
        if not url:
            return f"ERROR: Server '{server_name}' does not have a URL/SSE endpoint."

        meta = self.discover_oauth_metadata(url, server_cfg.get("headers", {}))
        auth_endpoint = meta.get("authorization_endpoint")
        token_endpoint = meta.get("token_endpoint")
        registration_endpoint = meta.get("registration_endpoint")

        if not auth_endpoint:
            return f"ERROR: Could not discover OAuth authorization endpoint for '{server_name}' at {url}."

        redirect_uri = f"http://localhost:{port}/callback"

        # PKCE code verifier and challenge (RFC 7636)
        code_verifier = secrets.token_urlsafe(64)
        hashed = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(hashed).decode("ascii").rstrip("=")

        client_id = "featherless-harness-client"

        # Dynamic client registration if supported
        if registration_endpoint:
            try:
                reg_payload = json.dumps({
                    "client_name": "featherless-harness",
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code"],
                    "response_types": ["code"],
                }).encode("utf-8")

                reg_req = urllib.request.Request(
                    registration_endpoint,
                    data=reg_payload,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(reg_req, timeout=10) as reg_resp:
                    reg_data = json.loads(reg_resp.read().decode("utf-8", errors="ignore"))
                    if "client_id" in reg_data:
                        client_id = reg_data["client_id"]
            except Exception as reg_err:
                logger.debug(f"Dynamic client registration skipped: {reg_err}")

        # Construct Authorization URL
        state = secrets.token_urlsafe(16)
        query_params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read write",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        login_url = f"{auth_endpoint}?{urllib.parse.urlencode(query_params)}"

        # Reset Callback Handler state
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.error = None

        # Start local HTTP server to receive redirect callback
        try:
            httpd = HTTPServer(("localhost", port), OAuthCallbackHandler)
            server_thread = Thread(target=httpd.serve_forever)
            server_thread.daemon = True
            server_thread.start()
        except Exception as e:
            return f"ERROR starting local OAuth callback listener on port {port}: {e}"

        logger.info(f"Opening browser for OAuth login: {login_url}")
        print(f"\n🔑 Opening browser for OAuth authentication with '{server_name}'...")
        print(f"URL: {login_url}\n")
        webbrowser.open(login_url)

        # Wait for callback
        import time
        elapsed = 0
        while elapsed < timeout_seconds:
            if OAuthCallbackHandler.auth_code:
                break
            if OAuthCallbackHandler.error:
                httpd.shutdown()
                return f"OAuth Authorization Failed: {OAuthCallbackHandler.error}"
            time.sleep(1)
            elapsed += 1

        code = OAuthCallbackHandler.auth_code
        httpd.shutdown()

        if not code:
            return f"OAuth authorization timed out after {timeout_seconds} seconds waiting for user login in browser."

        # Exchange authorization code for token if token endpoint is available
        access_token = code
        if token_endpoint:
            try:
                token_payload = urllib.parse.urlencode({
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                }).encode("utf-8")

                token_req = urllib.request.Request(
                    token_endpoint,
                    data=token_payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                with urllib.request.urlopen(token_req, timeout=10) as token_resp:
                    token_data = json.loads(token_resp.read().decode("utf-8", errors="ignore"))
                    access_token = token_data.get("access_token", code)
            except Exception as token_err:
                logger.warning(f"Token exchange warning: {token_err}. Using auth code directly.")

        # Persist and activate token
        self.set_server_token(server_name, access_token)
        return f"SUCCESS: Authenticated server '{server_name}' via OAuth. Token stored securely in .mcp_tokens.json."

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
                    auth_info = self.discover_oauth_metadata(url, headers)
                    if auth_info and auth_info.get("requires_auth"):
                        return (
                            f"🔒 [MCP OAuth Authentication Required for '{server_name}']\n"
                            f"Authorization Endpoint: {auth_info.get('authorization_endpoint')}\n"
                            f"Use tool call `authenticate_mcp_server(server_name='{server_name}')` to perform OAuth login."
                        )
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
