from pathlib import Path
from toolkit_adapters import ToolkitAdapter

adapter = ToolkitAdapter(r"C:\Users\edub\Documents\FileExplorer")

# Test get_file_overview with valid file
result = adapter.dispatch("get_file_overview", {"rel_path": "./app.py"})
print(result[:500])

# Test with directory (should reject)
result = adapter.dispatch("get_file_overview", {"rel_path": "."})
print(result)

# Test with non-existent file
result = adapter.dispatch("get_file_overview", {"rel_path": "nonexistent.py"})
print(result)