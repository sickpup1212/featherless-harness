import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class AgentProfile:
    """Represents an agent profile loaded from an AGENT.md file."""
    name: str
    description: str
    tools: List[str] = field(default_factory=list)
    system_message: str = ""
    path: Path = Path(".")
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert agent profile to summary dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "system_message": self.system_message,
            "path": str(self.path),
            "metadata": self.metadata,
        }


class AgentManager:
    """Manages AGENT.md discovery, parsing, and execution profile loading."""

    def __init__(self, agents_dirs: Optional[List[Path]] = None, project_root: Optional[Path] = None):
        self.project_root = Path(project_root or ".").resolve()

        self.agents_dirs: List[Path] = []
        if agents_dirs:
            for d in agents_dirs:
                p = Path(d).resolve()
                if p not in self.agents_dirs:
                    self.agents_dirs.append(p)

        # Default locations: project_root / 'agents', user home agents
        default_agents_dir = self.project_root / "agents"
        if default_agents_dir not in self.agents_dirs:
            self.agents_dirs.append(default_agents_dir)

        user_agents_dir = Path.home() / ".featherless" / "agents"
        if user_agents_dir not in self.agents_dirs:
            self.agents_dirs.append(user_agents_dir)

        self.agents: Dict[str, AgentProfile] = {}
        self.discover_agents()

    def _parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """Parse frontmatter (YAML-like or key-value block) and body from AGENT.md."""
        metadata = {}
        body = content

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)

            for line in fm_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip().lower()
                v = v.strip().strip("'\"")

                if v.startswith("[") and v.endswith("]"):
                    # Parse simple inline list [item1, item2]
                    items = [item.strip().strip("'\"") for item in v[1:-1].split(",") if item.strip()]
                    metadata[k] = items
                else:
                    metadata[k] = v

        return metadata, body.strip()

    def discover_agents(self) -> Dict[str, AgentProfile]:
        """Discover all AGENT.md files in registered directories and project root."""
        self.agents.clear()

        # Check registered agent directories
        for agents_dir in self.agents_dirs:
            if not agents_dir.exists() or not agents_dir.is_dir():
                continue

            for root, dirs, files in os.walk(agents_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for file in files:
                    if file.upper() in ("AGENT.MD", "AGENT.YML", "AGENT.YAML") or file.endswith(".AGENT.md"):
                        agent_file = Path(root) / file
                        self._load_agent_file(agent_file)

        # Also search project_root for AGENT.md files
        if self.project_root.exists():
            for root, dirs, files in os.walk(self.project_root):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in ("venv", ".venv", "__pycache__", "node_modules", "dist", "build")
                ]
                for file in files:
                    if file.upper() == "AGENT.MD":
                        agent_file = Path(root) / file
                        self._load_agent_file(agent_file)

        return self.agents

    def _load_agent_file(self, file_path: Path):
        """Load and register an AGENT.md file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            meta, system_message = self._parse_frontmatter(content)

            name = meta.get("name") or file_path.parent.name
            description = meta.get("description") or meta.get("desc") or f"Agent: {name}"
            tools = meta.get("tools", [])
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(",") if t.strip()]

            agent = AgentProfile(
                name=name,
                description=description,
                tools=tools,
                system_message=system_message,
                path=file_path.resolve(),
                metadata=meta,
            )
            self.agents[name] = agent
        except Exception as e:
            print(f"Failed to load agent profile at {file_path}: {e}")

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all available agents with summaries."""
        return [agent.to_dict() for agent in self.agents.values()]

    def get_agent(self, name: str) -> Optional[AgentProfile]:
        """Get an AgentProfile by name."""
        return self.agents.get(name)

    def get_agent_overview(self, name: str) -> str:
        """Get formatted Markdown summary of an agent profile."""
        agent = self.get_agent(name)
        if not agent:
            return f"ERROR: Agent '{name}' not found. Available agents: {list(self.agents.keys())}"

        lines = [
            f"## Agent Profile: {agent.name}",
            f"- **Description**: {agent.description}",
            f"- **Allowed Tools**: {', '.join(agent.tools) if agent.tools else 'All / Default'}",
            f"- **File Location**: `{agent.path}`",
            "",
            "### System Message:",
            agent.system_message
        ]
        return "\n".join(lines)
