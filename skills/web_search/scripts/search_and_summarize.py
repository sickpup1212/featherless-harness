#!/usr/bin/env python3
import sys
from pathlib import Path

# Ensure project root is in python path
sys.path.insert(0, str(Path.cwd()))

from web_search import WebSearchManager

def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Python 3.12 release notes"
    wsm = WebSearchManager()
    print(f"Executing web search for: '{query}'")
    results = wsm.search(query, max_results=3)
    print(results)

if __name__ == "__main__":
    main()
