"""Summarise interaction logs by condition (A = open questions, B = options + Other).

Usage:
    python scripts/summarise_logs.py                 # all files in logs/
    python scripts/summarise_logs.py --logs path/    # another folder
    python scripts/summarise_logs.py --min-answers 2 # ignore sessions with fewer answers

Prints a Markdown table for the report. With a handful of sessions this is a
pilot that shows what the system records, not evidence that one condition is better.
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_sessions(folder: Path) -> list[list[dict]]:
    sessions = []
    for path in sorted(folder.glob("session-*.jsonl")):
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass                     # a line cut off when the app was stopped
        if events and events[0].get("event") == "session_start":
            sessions.append(events)
    return sessions


def summarise(sessions: list[list[dict]], min_answers: int = 1) -> dict:
    by_cond = defaultdict(lambda: defaultdict(list))
    for events in sessions:
        cond = events[0].get("condition", "?")
        answers = [e for e in events
                   if e["event"] in ("answer_option", "answer_skip")
                   or (e["event"] == "answer_text" and e.get("slot"))]
        if len(answers) < min_answers:
            continue
        m = by_cond[cond]
        m["sessions"].append(1)
        m["questions"].append(sum(e["event"] == "question_shown" for e in events))
        m["clarify"].append(sum(e["event"] == "question_shown" and e.get("kind") == "clarify" for e in events))
        m["option_answers"].append(sum(e["event"] == "answer_option" for e in answers))
        m["typed_answers"].append(sum(e["event"] == "answer_text" for e in answers))
        m["skips"].append(sum(e["event"] == "answer_skip" for e in answers))
        m["unanswered"].append(sum(e["event"] == "question_unanswered" for e in events))
        m["edits"].append(sum(e["event"] == "slot_edited" for e in events))
        confirms = [e for e in events if e["event"] == "confirm_shown"]
        m["assumptions"].append(len(confirms[-1].get("assumptions", [])) if confirms else 0)
        m["reached_plan"].append(int(any(e["event"] == "plan_checked" and not e.get("errors") for e in events)))
        m["answer_seconds"].extend(e["latency_ms"] / 1000 for e in answers if e.get("latency_ms") is not None)
        m["typed_chars"].extend(e.get("chars", 0) for e in answers if e["event"] == "answer_text")
        m["plan_seconds"].extend(e["latency_ms"] / 1000 for e in events
                                 if e["event"] == "llm_call" and e.get("purpose") == "plan")
    return by_cond


def fmt_mean(values) -> str:
    return f"{statistics.mean(values):.1f}" if values else "–"


def fmt_median(values) -> str:
    return f"{statistics.median(values):.1f}" if values else "–"


def table(by_cond: dict) -> str:
    rows = [
        ("Sessions", lambda m: str(len(m["sessions"]))),
        ("Reached a checked plan", lambda m: f"{sum(m['reached_plan'])}/{len(m['sessions'])}"),
        ("Questions asked (mean per session)", lambda m: fmt_mean(m["questions"])),
        ("  of which clarify turns (mean)", lambda m: fmt_mean(m["clarify"])),
        ("Answers by option (mean)", lambda m: fmt_mean(m["option_answers"])),
        ("Answers typed (mean)", lambda m: fmt_mean(m["typed_answers"])),
        ("Questions skipped (mean)", lambda m: fmt_mean(m["skips"])),
        ("Answers that missed the question (mean)", lambda m: fmt_mean(m["unanswered"])),
        ("Edits in the side panel (mean)", lambda m: fmt_mean(m["edits"])),
        ("Assumptions at confirm (mean)", lambda m: fmt_mean(m["assumptions"])),
        ("Time to answer a question, s (median)", lambda m: fmt_median(m["answer_seconds"])),
        ("Length of typed answers, chars (mean)", lambda m: fmt_mean(m["typed_chars"])),
        ("Plan generation, s (median per call)", lambda m: fmt_median(m["plan_seconds"])),
    ]
    conds = [c for c in ("A", "B") if c in by_cond] + [c for c in by_cond if c not in ("A", "B")]
    names = {"A": "A: open questions", "B": "B: options + Other"}
    lines = ["| Measure | " + " | ".join(names.get(c, c) for c in conds) + " |",
             "|---|" + "---:|" * len(conds)]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(by_cond[c]) for c in conds) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logs", type=Path, default=ROOT / "logs")
    parser.add_argument("--min-answers", type=int, default=1,
                        help="skip sessions with fewer answered questions (default 1)")
    args = parser.parse_args(argv)
    if not args.logs.exists():
        print(f"No log folder at {args.logs}")
        return 1
    by_cond = summarise(load_sessions(args.logs), args.min_answers)
    if not by_cond:
        print("No sessions with answers found.")
        return 1
    print(table(by_cond))
    print("\nPilot only: too few sessions to compare the conditions statistically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
