#!/usr/bin/env python3
import sys
from pathlib import Path

def analyze_project(root: Path):
    print("=== Code Quality Analyzer ===")
    py_files = list(root.glob("**/*.py"))
    print(f"Total Python files found: {len(py_files)}")

    issues = 0
    for f in py_files:
        if ".venv" in f.parts or "venv" in f.parts:
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if "eval(" in content or "exec(" in content:
                print(f"⚠️  Potential security warning in {f.relative_to(root)}: contains eval/exec")
                issues += 1
        except Exception:
            pass

    if issues == 0:
        print("✅ No critical security warnings detected.")

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    analyze_project(target)
