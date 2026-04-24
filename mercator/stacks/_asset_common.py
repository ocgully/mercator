"""Shared asset-layer helpers used by all per-stack asset modules.

Kept deliberately small: a single extension → kind map, plus a `classify()`
function that picks the kind from a path. Stacks may layer their own
classification on top (e.g. Unity's `.asset` is ambiguous and handled in
`unity_assets.py`).

Bias: **precision over completeness.** If we can't confidently classify
something, we emit `"kind": "other"` rather than guess. Downstream agents
can filter on kind and trust what they see.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


# Extension → canonical kind. Lowercase keys; the leading dot is included.
EXT_KIND: Dict[str, str] = {
    # textures / images
    ".png": "texture", ".jpg": "texture", ".jpeg": "texture",
    ".gif": "texture", ".bmp": "texture", ".tga": "texture",
    ".tiff": "texture", ".tif": "texture", ".psd": "texture",
    ".webp": "texture", ".exr": "texture", ".hdr": "texture",
    ".ico": "texture",
    # vector
    ".svg": "vector",
    # 3D models
    ".fbx": "model", ".obj": "model", ".gltf": "model", ".glb": "model",
    ".dae": "model", ".3ds": "model", ".blend": "model", ".ply": "model",
    ".stl": "model", ".usd": "model", ".usdz": "model",
    # audio
    ".wav": "audio", ".mp3": "audio", ".ogg": "audio", ".flac": "audio",
    ".aiff": "audio", ".aif": "audio", ".m4a": "audio", ".opus": "audio",
    # video
    ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video",
    ".avi": "video",
    # shaders
    ".shader": "shader", ".cginc": "shader", ".hlsl": "shader",
    ".glsl": "shader", ".vert": "shader", ".frag": "shader",
    ".compute": "shader", ".wgsl": "shader", ".metal": "shader",
    # fonts
    ".ttf": "font", ".otf": "font", ".woff": "font", ".woff2": "font",
    # data
    ".json": "data", ".xml": "data", ".yaml": "data", ".yml": "data",
    ".toml": "data", ".csv": "data", ".tsv": "data",
    # localisation (handled separately by strings.json, but classify too)
    ".po": "locale", ".pot": "locale", ".arb": "locale", ".mo": "locale",
    # Unity-specific
    ".mat": "material", ".unity": "scene", ".prefab": "prefab",
    ".anim": "animation", ".controller": "animator",
    ".playable": "playable", ".asset": "asset", ".asmdef": "code",
    ".physicsmaterial": "physics", ".physicsmaterial2d": "physics",
    ".mask": "mask", ".cubemap": "texture", ".rendertexture": "texture",
    ".flare": "flare", ".guiskin": "ui", ".fontsettings": "font",
    ".terrainlayer": "terrain", ".lighting": "lighting",
    ".mixer": "audio", ".overrideController": "animator",
    ".spriteatlas": "texture", ".spriteatlasv2": "texture",
}


def classify(path: Path) -> Optional[str]:
    """Return the asset kind for `path`, or `None` if not recognised."""
    return EXT_KIND.get(path.suffix.lower())


def safe_size(path: Path) -> Optional[int]:
    """Return file size in bytes; `None` if the stat fails (broken symlink etc.)."""
    try:
        return path.stat().st_size
    except OSError:
        return None
