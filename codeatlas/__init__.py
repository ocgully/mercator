"""codeatlas — layered, AI-friendly codemap for agent consumption.

Public API (for agents that import the package rather than invoking the CLI):

    from codeatlas.query import systems, contract, symbol, deps, touches, system

Each returns a JSON-serialisable dict. See `codeatlas.cli` for the command
surface. Schema version is "1" — consumers check `meta.json.schema_version`.

Legacy `mercator` and `codemap` CLI entry points remain installed as
deprecation shims that print a warning and forward to `codeatlas`.
"""
__version__ = "0.6.0"
SCHEMA_VERSION = "1"
