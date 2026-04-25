# Systems Map

**Stack**: python
**Workspace members**: 5

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Systems

| System | Version | Kind | Workspace deps |
|--------|---------|------|----------------|
| `mercator` | 0.5.0 | p,a,c,k,a,g,e | mercator.render, mercator.stacks |
| `mercator.render` | None | p,a,c,k,a,g,e | mercator, mercator.render.atlas |
| `mercator.render.atlas` | None | p,a,c,k,a,g,e |  |
| `mercator.stacks` | None | p,a,c,k,a,g,e | mercator |
| `tests` | None | p,a,c,k,a,g,e | mercator |

## How agents use this data

Agents should query the CLI rather than reading this file directly:

```
mercator query systems                  # this view as JSON
mercator query deps <system>            # dependents + dependencies
mercator query touches <file-path>      # which system owns this path
mercator query system <name>            # Layer 1 + 2 slice for one system
```

