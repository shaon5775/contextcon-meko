"""Remove TEST memories from the Meko datapack (owner approved, 10 Nov 2026).
Only memories whose metadata run_tag starts with "eval-" or "review-live-" are touched (evaluation runs and live
review tests). Everything else (real fixes, knowledge, conversations) stays.
    python -u scripts/clean_test_memories.py          # dry run: only counts and lists
    python -u scripts/clean_test_memories.py --yes    # really delete
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402
from saathi.desk import AGENT_CASEWORKER, AGENT_TRIAGE  # noqa: E402

TEST_PREFIXES = ("eval-", "review-live-")


def _meta(row: dict) -> dict:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    return meta


def _rows(res, key: str) -> list:
    if isinstance(res, dict):
        return res.get(key) or res.get("results") or res.get("memories") or []
    return res or []


async def list_all(meko, conv: str, promoted: bool) -> list:
    rows, page = [], 1
    while True:
        res = await meko.call("memory_get_all", conversation_id=conv, agent_id=AGENT_CASEWORKER,
                              promoted=promoted, page=page, page_size=100)
        batch = _rows(res, "promoted_memories" if promoted else "memories")
        rows += batch
        total_pages = res.get("total_pages", 1) if isinstance(res, dict) else 1
        if not batch or page >= (total_pages or 1):
            return rows
        page += 1


async def full_meta(meko, conv: str, row: dict, show: bool) -> dict:
    """memory_get_all rows hide metadata (10 Nov 2026: only id/conversation_id/agent_id/data), so ask Meko for the
    full record of each memory. Returns {} when the record has no metadata or cannot be read."""
    if _meta(row):
        return _meta(row)
    try:
        rec = await meko.call("memory_get_by_id", memory_id=row["id"], conversation_id=conv,
                              agent_id=row.get("agent_id") or AGENT_CASEWORKER)
    except Exception as e:  # noqa: BLE001
        if show:
            print(f"   get_by_id failed for {row['id'][:8]}: {str(e)[:120]}")
        return {}
    if show and not getattr(full_meta, "shown", False):
        print("   SAMPLE get_by_id:", json.dumps(rec)[:700])
        full_meta.shown = True
    if isinstance(rec, dict):
        for cand in (rec, rec.get("memory") if isinstance(rec.get("memory"), dict) else None,
                     *(rec.get("results") or [] if isinstance(rec.get("results"), list) else [])):
            if isinstance(cand, dict) and _meta(cand):
                return _meta(cand)
    return {}


async def main() -> None:
    really = "--yes" in sys.argv
    show = "--show" in sys.argv
    meko, _, _ = build(offline=False)
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "clean test memories")
        for promoted in (False, True):
            rows = await list_all(meko, conv, promoted)
            metas = [await full_meta(meko, conv, r, show) for r in rows]
            for r, m in zip(rows, metas):
                r["metadata"] = m
            unknown = sum(1 for m in metas if not m)
            print(f"   (metadata unreadable for {unknown} of {len(rows)} rows; those are KEPT)")
            test = [r for r in rows if str(_meta(r).get("run_tag", "")).startswith(TEST_PREFIXES)]
            label = "promoted store" if promoted else "regular memories"
            print(f"== {label}: {len(rows)} total, {len(test)} test memories")
            tags = {}
            for r in test:
                tags[_meta(r)["run_tag"]] = tags.get(_meta(r)["run_tag"], 0) + 1
            print("   by run tag:", tags)
            if "--show" in sys.argv:
                fixes = [r for r in rows if "VERIFIED FIX" in json.dumps(r)]
                print(f"   rows mentioning VERIFIED FIX: {len(fixes)}")
                for r in (fixes or rows)[:2]:
                    print("   SAMPLE:", json.dumps(r)[:900])
            if not really:
                continue
            ok = fail = 0
            for r in test:
                try:
                    await meko.call("memory_delete_by_id", memory_id=r["id"], conversation_id=conv,
                                    agent_id=r.get("agent_id") or AGENT_CASEWORKER)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    if fail <= 3:
                        print(f"   could not delete {r['id'][:8]}: {str(e)[:160]}")
            print(f"   deleted {ok}, failed {fail}")
        print("DRY RUN only (nothing deleted). Add --yes to delete." if not really else "Done.")


if __name__ == "__main__":
    asyncio.run(main())
