# local_agent/toolkit/code_editor.py
import re
from typing import List, Tuple, Optional, Dict
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from code_reader import CodeReader


class EditOperation(Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"
    CREATE = "create"


@dataclass
class Edit:
    """Represents a single edit operation."""
    operation: EditOperation
    file_path: Path
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    new_content: Optional[str] = None
    old_content: Optional[str] = None
    description: str = ""
    original_context: Optional[str] = None  # Context around edit for verification

    def to_diff_format(self) -> str:
        """Generate a unified diff-like representation."""
        if self.operation == EditOperation.CREATE:
            return f"--- /dev/null\n+++ {self.file_path}\n+ {self.new_content}"

        lines = []
        lines.append(f"--- {self.file_path}")
        lines.append(f"+++ {self.file_path}")

        if self.original_context:
            old_lines = self.original_context.splitlines()
            new_lines = (self.new_content or "").splitlines()

            for line in old_lines:
                lines.append(f"- {line}")
            for line in new_lines:
                lines.append(f"+ {line}")

        return "\n".join(lines)

    def apply(self) -> bool:
        """Apply the edit to the file."""
        try:
            if self.operation == EditOperation.CREATE:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.file_path, 'w') as f:
                    f.write(self.new_content or "")
                return True

            if not self.file_path.exists():
                raise FileNotFoundError(f"File not found: {self.file_path}")

            with open(self.file_path, 'r') as f:
                lines = f.readlines()

            if self.operation == EditOperation.REPLACE:
                if self.start_line and self.end_line:
                    new_lines = lines[:self.start_line - 1]
                    if self.new_content:
                        content = self.new_content if self.new_content.endswith('\n') else self.new_content + '\n'
                        new_lines.extend(content.splitlines(keepends=True))
                    new_lines.extend(lines[self.end_line:])
                    lines = new_lines
                else:
                    # Replace by content match
                    if self.old_content and self.new_content:
                        content = ''.join(lines)
                        if self.old_content in content:
                            content = content.replace(self.old_content, self.new_content, 1)
                            lines = content.splitlines(keepends=True)

            elif self.operation == EditOperation.INSERT:
                if self.start_line and self.new_content:
                    content = self.new_content if self.new_content.endswith('\n') else self.new_content + '\n'
                    insert_lines = content.splitlines(keepends=True)
                    lines = lines[:self.start_line - 1] + insert_lines + lines[self.start_line - 1:]

            elif self.operation == EditOperation.DELETE:
                if self.start_line and self.end_line:
                    lines = lines[:self.start_line - 1] + lines[self.end_line:]

            with open(self.file_path, 'w') as f:
                f.writelines(lines)

            return True

        except Exception as e:
            print(f"Edit failed: {e}")
            return False


class CodeEditor:
    """Edit code files with safety checks and validation."""

    def __init__(self, project_root: Path, create_backup: bool = True, auto_apply: bool = False):
        self.project_root = Path(project_root).resolve()
        self.create_backup = create_backup
        self.auto_apply = auto_apply
        self.pending_edits: List[Edit] = []
        self.applied_edits: List[Edit] = []

    def _ensure_in_project(self, file_path: Path) -> Path:
        """Ensure the file is within the project root."""
        full_path = (self.project_root / file_path).resolve()
        try:
            full_path.relative_to(self.project_root)
            return full_path
        except ValueError:
            raise SecurityError(f"File {file_path} is outside project root")

    def _handle_edit(self, edit: Edit):
        """Queue or apply an edit based on auto_apply setting."""
        if self.auto_apply:
            if edit.operation != EditOperation.CREATE:
                self.backup_file(edit.file_path)
            if edit.apply():
                self.applied_edits.append(edit)
        else:
            self.pending_edits.append(edit)

    def backup_file(self, file_path: Path) -> Optional[Path]:
        """Create a backup of the file."""
        if not self.create_backup:
            return None

        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        try:
            with open(file_path, 'r') as src:
                with open(backup_path, 'w') as dst:
                    dst.write(src.read())
            return backup_path
        except Exception:
            return None

    def restore_backup(self, file_path: Path, backup_path: Path):
        """Restore a file from backup."""
        with open(backup_path, 'r') as src:
            with open(file_path, 'w') as dst:
                dst.write(src.read())

    def replace_lines(self, file_path: Path,
                      start_line: int, end_line: int,
                      new_content: str,
                      description: str = "") -> Edit:
        """Replace a range of lines."""
        file_path = self._ensure_in_project(file_path)

        editor = CodeReader(self.project_root)
        old_content = editor.read_file(file_path, start_line, end_line)

        edit = Edit(
            operation=EditOperation.REPLACE,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            new_content=new_content,
            old_content=old_content,
            description=description,
            original_context=editor.read_file(file_path,
                                               max(1, start_line - 3),
                                               end_line + 3)
        )
        self._handle_edit(edit)
        return edit

    def insert_after_line(self, file_path: Path,
                           after_line: int,
                           new_content: str,
                           description: str = "") -> Edit:
        """Insert content after a specific line."""
        file_path = self._ensure_in_project(file_path)

        edit = Edit(
            operation=EditOperation.INSERT,
            file_path=file_path,
            start_line=after_line + 1,
            new_content=new_content,
            description=description
        )
        self._handle_edit(edit)
        return edit

    def insert_before_symbol(self, file_path: Path,
                              symbol_name: str,
                              new_content: str,
                              description: str = "") -> Optional[Edit]:
        """Insert content before a symbol (function/class)."""
        editor = CodeReader(self.project_root)
        symbols = editor.analyze_file(file_path)

        for sym in symbols:
            if sym.name == symbol_name:
                return self.insert_after_line(
                    file_path,
                    sym.start_line - 1,
                    new_content,
                    description
                )
        return None

    def delete_lines(self, file_path: Path,
                     start_line: int, end_line: int,
                     description: str = "") -> Edit:
        """Delete a range of lines."""
        file_path = self._ensure_in_project(file_path)

        editor = CodeReader(self.project_root)
        old_content = editor.read_file(file_path, start_line, end_line)

        edit = Edit(
            operation=EditOperation.DELETE,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            old_content=old_content,
            description=description,
            original_context=editor.read_file(file_path,
                                               max(1, start_line - 3),
                                               end_line + 3)
        )
        self._handle_edit(edit)
        return edit

    def create_file(self, file_path: Path,
                    content: str,
                    description: str = "") -> Edit:
        """Create a new file."""
        file_path = self._ensure_in_project(file_path)

        # Check if file already exists
        if file_path.exists():
            raise FileExistsError(f"File already exists: {file_path}")

        edit = Edit(
            operation=EditOperation.CREATE,
            file_path=file_path,
            new_content=content,
            description=description
        )
        self._handle_edit(edit)
        return edit

    def replace_symbol_body(self, file_path: Path,
                            symbol_name: str,
                            new_body: str,
                            include_signature: bool = True,
                            description: str = "") -> Optional[Edit]:
        """Replace the body of a function or class."""
        editor = CodeReader(self.project_root)
        symbols = editor.analyze_file(file_path)

        for sym in symbols:
            if sym.name == symbol_name:
                start = sym.start_line if include_signature else min(sym.start_line + 1, sym.end_line)
                return self.replace_lines(
                    file_path,
                    start,
                    sym.end_line,
                    new_body,
                    description
                )

        return None

    def apply_pending_edits(self, review_changes: bool = True) -> List[Edit]:
        """Apply all pending edits with optional review."""
        applied = []

        for edit in list(self.pending_edits):
            if review_changes:
                print(f"\n{'='*60}")
                print(f"Edit: {edit.description}")
                print(f"File: {edit.file_path}")
                print(f"Operation: {edit.operation.value}")
                if edit.start_line:
                    print(f"Lines: {edit.start_line}-{edit.end_line or 'N/A'}")
                if edit.original_context:
                    print(f"\nContext:")
                    print(edit.original_context)
                if edit.new_content:
                    print(f"\nNew content:\n{edit.new_content}")
                print(f"{'='*60}")

                response = input("Apply this edit? (y/n): ")
                if response.lower() != 'y':
                    continue

            # Create backup before applying
            if edit.operation != EditOperation.CREATE:
                backup = self.backup_file(edit.file_path)

            if edit.apply():
                applied.append(edit)
                self.applied_edits.append(edit)

        self.pending_edits.clear()
        return applied

    def undo_last_edit(self) -> bool:
        """Undo the last applied edit."""
        if not self.applied_edits:
            return False

        edit = self.applied_edits.pop()

        try:
            if edit.operation == EditOperation.DELETE:
                # Restore deleted content
                if edit.start_line:
                    restore_edit = Edit(
                        operation=EditOperation.INSERT,
                        file_path=edit.file_path,
                        start_line=edit.start_line,
                        new_content=edit.old_content or ""
                    )
                    return restore_edit.apply()
            elif edit.operation == EditOperation.INSERT:
                # Remove inserted lines
                if edit.start_line:
                    num_lines = len((edit.new_content or "").splitlines())
                    end_line = edit.start_line + max(0, num_lines - 1)
                    del_edit = Edit(
                        operation=EditOperation.DELETE,
                        file_path=edit.file_path,
                        start_line=edit.start_line,
                        end_line=end_line
                    )
                    return del_edit.apply()
            elif edit.operation == EditOperation.REPLACE:
                # Restore old content
                if edit.old_content and edit.start_line:
                    num_new = len((edit.new_content or "").splitlines())
                    new_end = edit.start_line + max(0, num_new - 1)
                    repl_edit = Edit(
                        operation=EditOperation.REPLACE,
                        file_path=edit.file_path,
                        start_line=edit.start_line,
                        end_line=new_end,
                        new_content=edit.old_content
                    )
                    return repl_edit.apply()
            elif edit.operation == EditOperation.CREATE:
                # Delete the created file
                if edit.file_path.exists():
                    edit.file_path.unlink()
                return True

            return False
        except Exception:
            return False

    def get_pending_edits_summary(self) -> str:
        """Get a summary of pending edits."""
        if not self.pending_edits:
            return "No pending edits."

        lines = [f"## Pending Edits ({len(self.pending_edits)})"]

        for i, edit in enumerate(self.pending_edits, 1):
            lines.append(f"\n### Edit {i}: {edit.description}")
            lines.append(f"- File: `{edit.file_path.name}`")
            lines.append(f"- Operation: {edit.operation.value}")
            if edit.start_line:
                lines.append(f"- Lines: {edit.start_line}-{edit.end_line or 'end'}")
            if edit.new_content:
                lines.append(f"- New content ({len(edit.new_content)} chars):")
                lines.append("```")
                lines.append(edit.new_content[:200] + ("..." if len(edit.new_content) > 200 else ""))
                lines.append("```")

        return "\n".join(lines)


class SecurityError(Exception):
    """Raised when trying to edit files outside project root."""
    pass
