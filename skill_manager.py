import os
import re
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Skill:
    """Represents a loaded Skill with metadata, instructions, and resources."""
    name: str
    description: str
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    path: Path = Path(".")
    instructions: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert skill to a summary dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "path": str(self.path),
            "metadata": self.metadata,
        }


class SkillManager:
    """Manages skill discovery, loading, reference document reading, and script execution."""

    def __init__(self, skills_dirs: Optional[List[Path]] = None, project_root: Optional[Path] = None):
        self.project_root = Path(project_root or ".").resolve()

        self.skills_dirs: List[Path] = []
        if skills_dirs:
            for d in skills_dirs:
                p = Path(d).resolve()
                if p not in self.skills_dirs:
                    self.skills_dirs.append(p)

        # Default skill locations: project_root / 'skills', user home skills
        default_project_skills = self.project_root / "skills"
        if default_project_skills not in self.skills_dirs:
            self.skills_dirs.append(default_project_skills)

        user_skills = Path.home() / ".featherless" / "skills"
        if user_skills not in self.skills_dirs:
            self.skills_dirs.append(user_skills)

        self.skills: Dict[str, Skill] = {}
        self.discover_skills()

    def _parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """Parse frontmatter (YAML-like or key-value block) and body from SKILL.md."""
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
                    # Parse simple list
                    items = [item.strip().strip("'\"") for item in v[1:-1].split(",") if item.strip()]
                    metadata[k] = items
                else:
                    metadata[k] = v

        return metadata, body.strip()

    def discover_skills(self) -> Dict[str, Skill]:
        """Discover all SKILL.md files in registered skill directories."""
        self.skills.clear()

        for skills_dir in self.skills_dirs:
            if not skills_dir.exists() or not skills_dir.is_dir():
                continue

            for item in sorted(skills_dir.iterdir()):
                if item.is_dir():
                    skill_md = item / "SKILL.md"
                    if skill_md.exists() and skill_md.is_file():
                        try:
                            content = skill_md.read_text(encoding="utf-8", errors="replace")
                            meta, instructions = self._parse_frontmatter(content)

                            name = meta.get("name") or item.name
                            description = meta.get("description") or meta.get("desc") or f"Skill: {name}"
                            version = meta.get("version", "1.0.0")
                            tags = meta.get("tags", [])
                            if isinstance(tags, str):
                                tags = [t.strip() for t in tags.split(",") if t.strip()]

                            skill = Skill(
                                name=name,
                                description=description,
                                version=version,
                                tags=tags,
                                path=item.resolve(),
                                instructions=instructions,
                                metadata=meta,
                            )
                            self.skills[name] = skill
                        except Exception as e:
                            print(f"Failed to load skill at {skill_md}: {e}")

        return self.skills

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all available skills with summaries."""
        return [skill.to_dict() for skill in self.skills.values()]

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a Skill by name."""
        return self.skills.get(name)

    def get_skill_overview(self, name: str) -> str:
        """Get formatted Markdown summary of a skill, including resources and scripts."""
        skill = self.get_skill(name)
        if not skill:
            return f"ERROR: Skill '{name}' not found. Available: {list(self.skills.keys())}"

        lines = [
            f"## Skill: {skill.name} (v{skill.version})",
            f"- **Description**: {skill.description}",
            f"- **Location**: `{skill.path}`",
            f"- **Tags**: {', '.join(skill.tags) if skill.tags else 'None'}",
            ""
        ]

        # List resources (documents, reference specs, templates)
        resources = self.list_skill_resources(name)
        if resources:
            lines.append("### Available Resources/References:")
            for r in resources:
                lines.append(f"- `{r}`")
            lines.append("")

        # List executable scripts
        scripts = self.list_skill_scripts(name)
        if scripts:
            lines.append("### Available Executable Scripts:")
            for s in scripts:
                lines.append(f"- `{s}`")
            lines.append("")

        if skill.instructions:
            lines.append("### Skill Instructions:")
            lines.append(skill.instructions)

        return "\n".join(lines)

    def list_skill_resources(self, skill_name: str) -> List[str]:
        """List all reference documents and files in the skill directory."""
        skill = self.get_skill(skill_name)
        if not skill:
            return []

        resources = []
        for root, _, files in os.walk(skill.path):
            rel_root = Path(root).relative_to(skill.path)
            if rel_root.parts and rel_root.parts[0] in ("scripts", "tools"):
                continue  # Skip scripts directory
            for f in files:
                if f == "SKILL.md":
                    continue
                rel_path = rel_root / f if rel_root != Path(".") else Path(f)
                resources.append(str(rel_path))

        return sorted(resources)

    def list_skill_scripts(self, skill_name: str) -> List[str]:
        """List all executable scripts in the skill directory's scripts/ or tools/ folder."""
        skill = self.get_skill(skill_name)
        if not skill:
            return []

        scripts = []
        for script_dir_name in ("scripts", "tools"):
            s_dir = skill.path / script_dir_name
            if s_dir.exists() and s_dir.is_dir():
                for root, _, files in os.walk(s_dir):
                    rel_root = Path(root).relative_to(skill.path)
                    for f in files:
                        rel_path = rel_root / f
                        scripts.append(str(rel_path))

        return sorted(scripts)

    def read_skill_resource(self, skill_name: str, resource_rel_path: str) -> str:
        """Read a reference document or schema from a skill directory."""
        skill = self.get_skill(skill_name)
        if not skill:
            return f"ERROR: Skill '{skill_name}' not found."

        res_path = (skill.path / resource_rel_path).resolve()
        try:
            res_path.relative_to(skill.path)
        except ValueError:
            return f"ERROR: Resource '{resource_rel_path}' is outside skill directory."

        if not res_path.exists():
            return f"ERROR: Resource '{resource_rel_path}' not found in skill '{skill_name}'."

        if res_path.is_dir():
            return f"ERROR: Resource '{resource_rel_path}' is a directory."

        try:
            return res_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"ERROR reading skill resource: {e}"

    def execute_skill_script(self, skill_name: str, script_name: str, args: Optional[List[str]] = None) -> str:
        """Execute a script located within a skill directory."""
        skill = self.get_skill(skill_name)
        if not skill:
            return f"ERROR: Skill '{skill_name}' not found."

        script_path = (skill.path / script_name).resolve()
        try:
            script_path.relative_to(skill.path)
        except ValueError:
            return f"ERROR: Script '{script_name}' is outside skill directory."

        if not script_path.exists():
            return f"ERROR: Script '{script_name}' not found in skill '{skill_name}'."

        cmd = []
        if script_path.suffix == ".py":
            cmd = ["python3", str(script_path)]
        elif script_path.suffix in (".sh", ".bash"):
            cmd = ["bash", str(script_path)]
        else:
            cmd = [str(script_path)]

        if args:
            cmd.extend([str(a) for a in args])

        try:
            res = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60
            )
            output = res.stdout
            if res.stderr:
                output += f"\nSTDERR:\n{res.stderr}"
            return output if output.strip() else "Script executed successfully with no output."
        except Exception as e:
            return f"ERROR executing skill script: {e}"
