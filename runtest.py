from pathlib import Path
from toolkit_adapters import ToolkitAdapter

target_path = Path(r"C:\Users\edub\Documents\FileExplorer")
if not target_path.exists():
    target_path = Path(".").resolve()

adapter = ToolkitAdapter(str(target_path))

# Test get_file_overview with valid file
result = adapter.dispatch("get_file_overview", {"rel_path": "./filesystem.py"})
print(result[:500])

# Test with directory (should reject)
result = adapter.dispatch("get_file_overview", {"rel_path": "."})
print(result)

# Test with non-existent file
result = adapter.dispatch("get_file_overview", {"rel_path": "nonexistent.py"})
print(result)
