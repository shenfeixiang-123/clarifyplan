"""Run the fixed extraction cases against DeepSeek and print a score.

Usage (needs DEEPSEEK_API_KEY in .env):
    python scripts/run_prompt_cases.py

Change one thing in core/prompts.py at a time, bump PROMPT_VERSION, rerun,
and copy the score line into docs/prompt_log.md (Lecture 09 testing loop).
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.llm import LLMError, call_json  # noqa: E402
from core.prompts import PROMPT_VERSION, build_extract_messages  # noqa: E402
from core.slots import empty_slots  # noqa: E402
from core.validator import clean_extraction  # noqa: E402


def check(expect, got_slot) -> bool:
    if isinstance(expect, dict):          # {"contains": [...], "not_contains": [...]} on the value text
        text = str(got_slot["value"] if got_slot else "").lower()
        return (all(w in text for w in expect.get("contains", []))
                and not any(w in text for w in expect.get("not_contains", [])))
    if expect in ("missing", "ambiguous", "stated"):
        status = got_slot["status"] if got_slot else "missing"
        return status == expect
    value = got_slot["value"] if got_slot else None
    if isinstance(expect, list):
        return value is not None and sorted(v.lower() for v in value) == sorted(e.lower() for e in expect)
    if isinstance(expect, (int, float)):
        return value is not None and float(value) == float(expect)
    return value is not None and str(value).lower() == str(expect).lower()


def main() -> None:
    spec = json.loads((ROOT / "tests" / "prompt_cases.json").read_text(encoding="utf-8"))
    today = date.fromisoformat(spec["today"])
    passed = total = 0
    for case in spec["cases"]:
        slots = empty_slots()
        for name, value in case.get("current", {}).items():   # facts already known before this message
            slots[name].update(value=value, status="stated")
        messages = build_extract_messages(today.isoformat(), slots, case.get("last_question"), case["text"])
        try:
            data, _ = call_json("extract", messages)
        except LLMError as exc:
            print(f"{case['id']}  ERROR  {exc}")
            total += len(case["expect"])
            continue
        updates = clean_extraction(data, today)
        for slot, expect in case["expect"].items():
            ok = check(expect, updates.get(slot))
            passed += ok
            total += 1
            got = updates.get(slot, {"status": "missing", "value": None})
            print(f"{case['id']}  {'PASS' if ok else 'FAIL'}  {slot:16} expected={expect!r:28} "
                  f"got={got.get('value')!r} ({got.get('status')})")
    print(f"\nprompt {PROMPT_VERSION}: {passed}/{total} checks passed")


if __name__ == "__main__":
    main()
