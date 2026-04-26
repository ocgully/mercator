---
description: Surface CodeAtlas structural context for the systems touched by the request
---

If the user's request mentions a file path, run `codeatlas query touches <path>` to identify the owning system, then `codeatlas query system <name>` for the composite slice (entry + deps + contract). Otherwise, run `codeatlas query systems` for the system roster. Surface any boundary violations via `codeatlas query violations`.

This is a read-only command. To make architectural changes, route through `@architect` (or `@orchestrator` if installed).
