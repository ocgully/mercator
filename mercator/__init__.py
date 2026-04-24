"""mercator — layered, AI-friendly codemap for agent consumption.

Previously shipped as `codemap`. Renamed to honour Gerardus Mercator, who
published the first book to use "atlas" as the term for a collection of
maps. Ecosystem rhythm is now: mercator · hopewell · pedia.

Public API (for agents that import the package rather than invoking the CLI):

    from mercator.query import systems, contract, symbol, deps, touches, system

Each returns a JSON-serialisable dict. See `mercator.cli` for the command
surface. Schema version is "1" — consumers check `meta.json.schema_version`.
"""
__version__ = "0.5.0"
SCHEMA_VERSION = "1"
