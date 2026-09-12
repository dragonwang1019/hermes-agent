#!/usr/bin/env python3
"""Write `$HERMES_HOME/cache/skill_recent.json` — the per-category "recently used" hint.

A count-only skills-index line (`library [count only]: 79 skills`) costs the model its passive view
of that category's names.  This file gives back the few entries that actually get loaded, at ~80
bytes a line instead of ~2000.  `agent/prompt_builder.py::_recent_skill_hint` reads it; a missing
or stale (older than `_RECENT_HINT_MAX_AGE_DAYS`) file simply renders no hint.

Source of truth is real usage: `skill_view` calls recorded in the session DB over the last 30 days.
Read-only on the DB, writes one small JSON — safe to run from cron.

Usage:
    python scripts/skill_recent_hint.py
"""

from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hermes_constants import get_hermes_home  # noqa: E402

WINDOW_DAYS = 30
PER_CATEGORY = 3


def view_counts(db, days: int = WINDOW_DAYS) -> "collections.Counter[str]":
    """`skill_view(name)` call counts over the last `days`, parsed from assistant tool_calls."""
    counts: "collections.Counter[str]" = collections.Counter()
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"state.db unavailable: {e}")
        return counts
    cut = time.time() - days * 86400
    try:
        rows = con.execute(
            "select tool_calls from messages where role='assistant' and tool_calls like '%skill_view%' "
            "and timestamp > ?", (cut,))
        for (raw,) in rows:
            try:
                calls = json.loads(raw or "[]")
            except Exception:
                continue
            for call in calls:
                fn = (call or {}).get("function") or {}
                if fn.get("name") != "skill_view":
                    continue
                try:
                    name = (json.loads(fn.get("arguments") or "{}")).get("name")
                except Exception:
                    name = None
                if name:
                    counts[str(name)] += 1
    except sqlite3.Error as e:
        print(f"state.db query failed: {e}")
    finally:
        con.close()
    return counts


def build_payload(counts, catalog: dict) -> dict:
    """`{category: [top N names by usage]}` for every category with real usage."""
    per_cat: dict = collections.defaultdict(list)
    for name, n in counts.items():
        cat = catalog.get(name)
        if cat and n:
            per_cat[cat].append((n, name))
    by_category = {cat: [n for _, n in sorted(hits, key=lambda x: (-x[0], x[1]))[:PER_CATEGORY]]
                   for cat, hits in per_cat.items()}
    return {"generated": time.time(), "window_days": WINDOW_DAYS,
            "source": "state.db skill_view call counts", "by_category": dict(sorted(by_category.items()))}


def main() -> int:
    from tools.skills_tool import _find_all_skills

    counts = view_counts(get_hermes_home() / "state.db")
    catalog = {s["name"]: (s.get("category") or "") for s in _find_all_skills()}
    payload = build_payload(counts, catalog)

    path = get_hermes_home() / "cache" / "skill_recent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")     # same-dir rename so readers never see a half file
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    total = sum(len(v) for v in payload["by_category"].values())
    print(f"skill_recent.json: {len(payload['by_category'])} categories, {total} names "
          f"(from {sum(counts.values())} skill_view calls in {WINDOW_DAYS}d)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
