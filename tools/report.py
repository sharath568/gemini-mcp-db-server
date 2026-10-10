"""Print the block-rate tables (Markdown) for the README/article:  python tools/report.py"""

import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_db_server.attack import run_all, summarize  # noqa: E402
from mcp_db_server.db import Database  # noqa: E402


async def main() -> None:
    db = Database()
    results = await run_all(db)
    await db.close()
    s = summarize(results)

    print(f"**Attacks blocked: {s['blocked_full_stack']}/{s['attacks']} with every layer, "
          f"{s['blocked_db_only']}/{s['attacks']} by the database alone (guard off).** "
          f"Legit queries allowed: {s['legit_allowed']}/{s['legit']}.\n")

    print("| Category | Cases | Stopped by (all layers) | Stopped by (guard off) |")
    print("|---|---:|---|---|")
    by_cat = defaultdict(list)
    for r in results:
        if r.expect == "blocked":
            by_cat[r.category].append(r)
    for cat, rows in by_cat.items():
        full = ", ".join(f"{k} {v}" for k, v in Counter(r.full_stack for r in rows).most_common())
        dbo = ", ".join(f"{k} {v}" for k, v in Counter(r.db_only for r in rows).most_common())
        print(f"| {cat} | {len(rows)} | {full} | {dbo} |")

    if s["only_guard_stopped"]:
        print("\nOnly the guard stopped these (the database would have answered):\n")
        for r in results:
            if r.id in s["only_guard_stopped"]:
                print(f"- `{r.id}` {r.category}: `{r.sql}`")
    if s["false_positives"]:
        print("\nLegit queries the guard wrongly blocked:", ", ".join(s["false_positives"]))


if __name__ == "__main__":
    asyncio.run(main())
