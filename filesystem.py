import os
import pathlib
import hashlib
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileNode:
    """Represents a file or directory in the project tree."""
    path: pathlib.Path
    name: str
    is_dir: bool
    size: int
    modified: datetime
    hash: Optional[str] = None
    children: Optional[List["FileNode"]] = None

    def to_tree_string(self, prefix: str = "", is_last: bool = True,
                       is_root: bool = True) -> str:
        """Generate a tree-view string representation."""
        if not self.is_dir:
            return f"{prefix}{'└── ' if is_last else '├── '}{self.name}"

        lines = []
        connector = "└── " if is_last else "├── "

        if is_root:
            lines.append(f"{self.name}/")
        else:
            lines.append(f"{prefix}{connector}{self.name}/")

        if self.children:
            new_prefix = prefix + ("    " if is_last else "│   ")
            for i, child in enumerate(self.children):
                child_is_last = i == len(self.children) - 1
                lines.append(child.to_tree_string(new_prefix, child_is_last, False))

        return "\n".join(lines)


class ProjectExplorer:
    """Explore and index a local project directory."""

    # Common patterns to ignore
    DEFAULT_IGNORES = {
        "__pycache__", ".git", ".venv", "venv", "node_modules",
        ".next", "dist", "build", ".tox", ".eggs", "*.egg-info",
        ".idea", ".vscode", "*.pyc", ".pytest_cache"
    }

    # Binary file extensions to skip
    BINARY_EXTENSIONS = {
        '.pyc', '.pyo', '.so', '.dll', '.exe', '.bin', '.dat',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.tar',
        '.gz', '.bz2', '.xz', '.rar', '.7z', '.woff', '.woff2',
        '.ttf', '.eot', '.mp3', '.mp4', '.avi', '.mov'
    }

    def __init__(self, root_path: str, ignores: Optional[Set[str]] = None):
        self.root = pathlib.Path(root_path).resolve()
        self.ignores = self.DEFAULT_IGNORES | (ignores or set())
        self._index: Dict[pathlib.Path, FileNode] = {}

    def explore(self, max_depth: Optional[int] = None,
                include_binary: bool = False) -> FileNode:
        """Build a tree index of the project."""
        if not self.root.exists():
            raise FileNotFoundError(f"Project root not found: {self.root}")

        self._index = {}
        root_node = self._build_node(self.root, max_depth, 0, include_binary)
        return root_node

    def _build_node(self, path: pathlib.Path, max_depth: Optional[int],
                    current_depth: int, include_binary: bool) -> FileNode:
        """Recursively build the file tree."""
        stat = path.stat()

        # Check if should ignore
        if path.name in self.ignores:
            node = FileNode(
                path=path, name=path.name, is_dir=path.is_dir(),
                size=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime)
            )
            self._index[path] = node
            return node

        if max_depth is not None and current_depth >= max_depth and path.is_dir():
            node = FileNode(
                path=path, name=path.name, is_dir=True,
                size=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime)
            )
            self._index[path] = node
            return node

        if path.is_dir():
            children = []
            try:
                for item in sorted(path.iterdir(), key=lambda p: p.name):
                    # Skip ignored directories
                    if item.name in self.ignores:
                        continue
                    child = self._build_node(item, max_depth, current_depth + 1, include_binary)
                    if child:
                        children.append(child)
            except PermissionError:
                pass

            node = FileNode(
                path=path, name=path.name, is_dir=True,
                size=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime),
                children=children
            )
            self._index[path] = node
            return node
        else:
            # File node
            ext = path.suffix.lower()
            if not include_binary and ext in self.BINARY_EXTENSIONS:
                return None

            file_hash = self._compute_hash(path) if self._should_hash(path) else None

            node = FileNode(
                path=path, name=path.name, is_dir=False,
                size=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime),
                hash=file_hash
            )
            self._index[path] = node
            return node

    def _compute_hash(self, path: pathlib.Path, algorithm: str = "sha256") -> str:
        """Compute file hash for change detection."""
        hasher = hashlib.new(algorithm)
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError):
            return ""

    def _should_hash(self, path: pathlib.Path) -> bool:
        """Determine if a file should be hashed."""
        ext = path.suffix.lower()
        return ext in {'.py', '.js', '.ts', '.jsx', '.tsx', '.rb', '.go', '.rs',
                       '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.swift', '.kt',
                       '.yaml', '.yml', '.json', '.toml', '.cfg', '.ini', '.xml',
                       '.html', '.css', '.scss', '.less', '.md', '.txt', '.sh',
                       '.bash', '.zsh', '.sql', '.graphql', '.proto', '.dockerfile',
                       '.env', '.lock'}

    def get_tree_string(self, max_depth: Optional[int] = 3) -> str:
        """Get a string representation of the project tree."""
        root = self.explore(max_depth)
        return root.to_tree_string()

    def find_files(self, pattern: Optional[str] = None, extension: Optional[str] = None,
                   max_depth: Optional[int] = None) -> List[pathlib.Path]:
        """Find files matching a pattern."""
        results = []
        root = self.explore(max_depth)

        def search(node: FileNode):
            if not node.is_dir:
                matches = True
                if extension and node.path.suffix != extension:
                    matches = False
                if pattern and pattern not in node.name:
                    matches = False

                if matches:
                    results.append(node.path)
            elif node.children:
                for child in node.children:
                    search(child)

        search(root)
        return results

    def get_recent_changes(self, since: datetime) -> List[FileNode]:
        """Get files modified since a given time."""
        results = []
        for node in self._index.values():
            if not node.is_dir and node.modified > since:
                results.append(node)
        return sorted(results, key=lambda n: n.modified, reverse=True)
