#!/usr/bin/env python3
"""Warm up (or rebuild) the skill_search vector index.

`skill_search` embeds the skill catalog with a LOCAL Ollama model and caches the vectors under
`$HERMES_HOME/cache/skill_search_index.npz`.  The tool notices a changed catalog by itself and
rebuilds inline, so this script is only about latency: run it after adding or editing skills and
the next `skill_search` call is instant instead of paying the embed pass.

Usage:
    python scripts/skill_search_warmup.py [--force]

Exit status 1 means no local embedder answered — `skill_search` then uses its lexical fallback.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tools.skills_tool import (  # noqa: E402
    _SKILL_SEARCH_DEFAULT_MODEL,
    _SKILL_SEARCH_DEFAULT_URL,
    _skill_search_build,
    _skill_search_catalog,
    _skill_search_index_file,
    _skill_search_signature,
)


def index_is_current(path, skills) -> bool:
    """True when the stored index matches the catalog and model — no rebuild needed."""
    if not path.exists():
        return False
    try:
        import numpy as np
        with np.load(path, allow_pickle=False) as z:   # NpzFile is only readable inside the block
            signature, model = str(z["signature"]), str(z["model"])
    except Exception as e:
        print(f"skill_search index unreadable ({e}); rebuilding")
        return False
    return signature == _skill_search_signature(skills) and model == _SKILL_SEARCH_DEFAULT_MODEL


def main(args=None) -> int:
    ap = argparse.ArgumentParser(description="Warm up the skill_search vector index.")
    ap.add_argument("--force", action="store_true", help="rebuild even when the index is current")
    opts = ap.parse_args(args)

    skills, path = _skill_search_catalog(), _skill_search_index_file()
    if not opts.force and index_is_current(path, skills):
        print(f"skill_search index up to date ({len(skills)} skills, {path.stat().st_size // 1024} KB)")
        return 0

    t0 = time.time()
    built = _skill_search_build(skills, _SKILL_SEARCH_DEFAULT_MODEL, _SKILL_SEARCH_DEFAULT_URL)
    if built is None:
        print(f"no local embedder at {_SKILL_SEARCH_DEFAULT_URL} (model {_SKILL_SEARCH_DEFAULT_MODEL}); "
              f"skill_search will use its lexical fallback")
        return 1
    size = path.stat().st_size if path.exists() else 0
    print(f"built skill_search index: {len(built['names'])} skills in {time.time() - t0:.1f}s "
          f"({size // 1024} KB, model {built['model']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
