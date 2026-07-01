"""
English product names -> product_meta.item_name_en.

Rules the translations must follow (see PROMPT):
  - generic product words are TRANSLATED   (חלב -> Milk, לחם -> Bread)
  - brand names are TRANSLITERATED         (במבה -> Bamba, תנובה -> Tnuva)
  - units are converted                    (גרם -> g, מ"ל -> ml, ליטר -> L)

Two modes:

  --apply file.json      Load ready-made translations
                         [{"code": "<barcode>", "en": "<name>"}, ...]
                         (used for the curated top-products batch).

  --run [--limit N]      Translate every product whose item_name_en is NULL by
                         calling Claude in chunks. Transport is auto-detected:
                           1. ANTHROPIC_API_KEY + `anthropic` package -> Messages API
                           2. logged-in `claude` CLI                  -> claude -p
                         Resumable: already-translated rows are skipped, results
                         are committed after every chunk.

    python scripts/translate_names.py --apply translations.json
    python scripts/translate_names.py --run --limit 200   # test slice
    python scripts/translate_names.py --run               # the whole catalog
"""

import _bootstrap  # noqa: F401
import json
import os
import re
import subprocess
import sys

from app.db import get_db, init_db

MODEL = os.environ.get("ZOLPO_TRANSLATE_MODEL", "claude-opus-4-8")
CHUNK = 120   # names per request: big enough to amortise, small enough to stay exact

PROMPT = """You translate Israeli supermarket product names from Hebrew to English \
for product cards in a price-comparison app.

Rules:
- TRANSLATE generic product words: חלב -> Milk, לחם -> Bread, גבינה -> Cheese, \
שמן זית -> Olive Oil, כתוש -> Crushed, שומן -> Fat.
- TRANSLITERATE brand names, never translate their meaning: במבה -> Bamba, \
ביסלי -> Bissli, תנובה -> Tnuva, אסם -> Osem, עלית -> Elite, שטראוס -> Strauss, \
טרה -> Tara, יטבתה -> Yotvata, תלמה -> Telma, ויסוצקי -> Wissotzky, \
זוגלובק -> Zoglowek, מגדים -> Migdim, פינוק -> Pinuk, קליק -> Klik, \
פסק זמן -> Pesek Zman, מקופלת -> Mekupelet, פרה (שוקולד) -> Para.
- Units: גרם/גר -> g, ק"ג -> kg, מ"ל/מל -> ml, ליטר -> L, יח' -> pcs; \
keep every number and percentage exactly (5% -> 5%).
- Names are often truncated mid-word; translate what is clearly there, do not invent.
- Style: short product-card label, Title Case for words, no trailing period, \
no comments, no Hebrew letters in the output.

Input: a JSON array [{"i": <int>, "he": "<hebrew name>"}, ...].
Output: ONLY a JSON array [{"i": <int>, "en": "<english name>"}, ...] with exactly \
the same indexes, valid JSON, nothing else."""

_HEBREW = re.compile(r"[֐-׿]")


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #

def _via_api(payload: str) -> str:
    import anthropic  # raises ImportError with a clear message if missing
    client = anthropic.Anthropic()
    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        system=PROMPT,
        messages=[{"role": "user", "content": payload}],
    ) as stream:
        return stream.get_final_message().content[-1].text


def _via_cli(payload: str) -> str:
    r = subprocess.run(
        ["claude", "-p", "--model", MODEL, PROMPT],
        input=payload, capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0 or "Not logged in" in r.stdout + r.stderr:
        raise RuntimeError(f"claude CLI failed: {(r.stdout + r.stderr)[:200]}")
    return r.stdout


def pick_transport():
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
            return _via_api, f"Messages API ({MODEL})"
        except ImportError:
            print("ANTHROPIC_API_KEY is set but `anthropic` is not installed:\n"
                  "    .venv312/bin/pip install anthropic")
    probe = subprocess.run(["claude", "-p", "--model", MODEL, "Reply with exactly: ok"],
                           capture_output=True, text=True, timeout=120)
    if probe.returncode == 0 and "Not logged in" not in probe.stdout + probe.stderr:
        return _via_cli, f"claude CLI ({MODEL})"
    sys.exit("No transport available. Either:\n"
             "  export ANTHROPIC_API_KEY=...  (+ pip install anthropic), or\n"
             "  log the claude CLI in once:  claude /login")


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #

def _parse_reply(text: str, expected: set[int]) -> dict[int, str]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return {}
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return {}
    out = {}
    for it in items:
        i, en = it.get("i"), (it.get("en") or "").strip()
        # Reject empties and anything that still contains Hebrew.
        if i in expected and en and not _HEBREW.search(en):
            out[i] = en
    return out


def save(pairs: list[tuple[str, str]]) -> int:
    """[(item_code, english_name)] -> product_meta (never overwrites)."""
    with get_db() as conn:
        for code, en in pairs:
            conn.execute(
                """
                INSERT INTO product_meta (item_code, item_name_en)
                VALUES (?, ?)
                ON CONFLICT(item_code) DO UPDATE SET
                    item_name_en = COALESCE(product_meta.item_name_en, excluded.item_name_en)
                """,
                (code, en),
            )
    return len(pairs)


def untranslated(limit: int | None) -> list[tuple[str, str]]:
    sql = ("SELECT p.item_code, p.item_name FROM products p "
           "LEFT JOIN product_meta m ON m.item_code = p.item_code "
           "WHERE m.item_name_en IS NULL ORDER BY p.item_code")
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_db() as conn:
        return [(r["item_code"], r["item_name"]) for r in conn.execute(sql)]


def run(limit: int | None) -> None:
    transport, label = pick_transport()
    todo = untranslated(limit)
    print(f"{len(todo):,} names to translate via {label}, chunk={CHUNK}", flush=True)

    done = failed = 0
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start:start + CHUNK]
        payload = json.dumps(
            [{"i": i, "he": name} for i, (_, name) in enumerate(chunk)],
            ensure_ascii=False,
        )
        try:
            reply = _parse_reply(transport(payload), set(range(len(chunk))))
        except Exception as e:
            print(f"  chunk @{start}: transport error, skipping ({e})", flush=True)
            failed += len(chunk)
            continue
        pairs = [(chunk[i][0], en) for i, en in reply.items()]
        done += save(pairs)
        failed += len(chunk) - len(pairs)
        print(f"  {min(start + CHUNK, len(todo)):,}/{len(todo):,}  saved={done:,} failed={failed:,}",
              flush=True)

    print(f"\nDone: {done:,} translated, {failed:,} left for a retry "
          f"(just run the script again).", flush=True)


def apply_file(path: str) -> None:
    data = json.load(open(path, encoding="utf-8"))
    pairs = [(d["code"], d["en"].strip()) for d in data
             if d.get("code") and d.get("en") and not _HEBREW.search(d["en"])]
    n = save(pairs)
    print(f"Applied {n:,} translations from {path} "
          f"({len(data) - n:,} skipped as empty/Hebrew/duplicate-safe).")


if __name__ == "__main__":
    init_db()
    argv = sys.argv[1:]
    if "--apply" in argv:
        apply_file(argv[argv.index("--apply") + 1])
    elif "--run" in argv:
        lim = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
        run(lim)
    else:
        print(__doc__)
