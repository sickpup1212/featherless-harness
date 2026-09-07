# Web Search Provider Guide for LLMs

## Recommended API Providers

| Provider | Environment Variable | Key Benefits |
|---|---|---|
| **Tavily AI** | `TAVILY_API_KEY` | Purpose-built for LLM RAG/Agents. Cleans HTML, extracts markdown, returns direct answers. |
| **Exa AI** | `EXA_API_KEY` | Neural link search, excellent for technical repos and documentation. |
| **Serper.dev** | `SERPER_API_KEY` | Real-time Google Search JSON results (~200ms latency). |
| **Brave Search** | `BRAVE_API_KEY` | High-quality independent index, privacy-focused. |
| **DuckDuckGo** | *(None required)* | Keyless fallback built into the framework. |
