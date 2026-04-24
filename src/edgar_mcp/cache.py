from __future__ import annotations

from pathlib import Path

import diskcache  # type: ignore[import-untyped]

_CACHE_DIR = Path.home() / ".cache" / "edgar-mcp"

disk_cache: diskcache.Cache = diskcache.Cache(str(_CACHE_DIR))
