"""Prompts for the two model calls.

Instruction (stable, written by the designer, versioned in git) is kept in the
system message; information (different on every call, assembled by code) is
kept in the user message (Lecture 09, instruction vs information).
DeepSeek JSON mode requires the word 'json' and an example of the output.

Change PROMPT_VERSION whenever you edit a prompt, and note it in docs/prompt_log.md.
"""
from __future__ import annotations

import json

PROMPT_VERSION = "v0.7"

EXTRACT_SYSTEM = """You read what a student wrote to a revision-planning assistant and extract facts into json.

Task: fill these fields only from what the student actually wrote in THIS message,
using TODAY to turn relative dates ("next Tuesday", "in 10 days") into YYYY-MM-DD.

Fields:
- exam_date: date of the FIRST exam, YYYY-MM-DD.
- subjects: the COMPLETE list of subjects to revise after this message. If the student adds a
  subject ("also", "too", "as well", "and"), return the subjects in CURRENT UNDERSTANDING plus
  the new one. If they replace or remove one ("instead", "only", "not X"), return the new list.
- daily_hours: number of hours per day the student can study.
- priority_subject: the one subject that needs most work, or "none" if they say all are equal.
- constraints: when the student CANNOT study, in their own meaning, or "none" if they say there are none.
  If they name times they can't study, write "no study on <days and times>" ("no study on Saturdays",
  "no study on weekday mornings"). Write "only <days or times>" ONLY if they say only/just
  ("only weekday evenings"). Never turn a time they can't study into a list of times they can,
  and never add days or times they did not mention.

Rules:
- status "stated": the student clearly gave this. Put a short quote in evidence.
- status "ambiguous": the student mentioned it but too vaguely to use (e.g. "a few hours",
  "sometime next month", "the usual subjects"). value must be null. In note, say what is
  unclear in at most 8 plain words addressed to the student, e.g. "how many hours is unclear"
  or "you sounded unsure". The note is shown next to the student's words, so do not repeat
  them, and never write "the student".
- status "missing": not mentioned. value must be null.
- Weekday names are not ambiguous: "next Tuesday", "this Tuesday" and "on Tuesday" all mean
  the first Tuesday after TODAY; "Tuesday after next" means the second one. Mark these "stated".
  (The student sees the resolved date before any plan is made and can correct it.)
- One message can answer several fields. "about 2 hours on weekdays" gives daily_hours 2 AND
  constraints "no study at weekends". Fill every field the message answers.
- Never guess or fill in a typical value. A null value is better than a guess.
- Do not include facts from the "current understanding" unless the student restates or changes them.
- If the student corrects an earlier fact, report the new value as "stated".

Output json exactly in this shape:
{
  "slots": {
    "exam_date": {"value": "2026-11-24", "status": "stated", "evidence": "my maths exam is on 24 November", "note": null},
    "subjects": {"value": ["Maths"], "status": "stated", "evidence": "my maths exam", "note": null},
    "daily_hours": {"value": null, "status": "ambiguous", "evidence": "a few hours", "note": "how many hours is unclear"},
    "priority_subject": {"value": null, "status": "missing", "evidence": null, "note": null},
    "constraints": {"value": null, "status": "missing", "evidence": null, "note": null}
  }
}"""

PLAN_SYSTEM = """You write a day-by-day revision timetable for one student and return it as json.

Task: plan revision on the dates listed under AVAILABLE DATES, using only the facts given
under STUDENT FACTS. The system has already removed days after the window and days off.

Rules:
- Use only dates from AVAILABLE DATES. You may leave some of them out.
- Each day's total minutes must not exceed daily_hours * 60.
- Every subject must appear at least once.
- If priority_subject names a subject, give it the most total time.
- Sessions have no clock time. A constraint about part of a day ("no study on weekday mornings",
  "evenings only") does not remove that day: plan it as usual, and the student fits the sessions
  into the free part of the day.
- Only list days that have at least one session; leave days off out of "days".
- Write summary and assumptions for the student. Never mention earlier attempts, corrections or these rules.
- Do not invent facts (topics, exam boards, grades). Use general focus labels such as
  "past paper", "review notes", "practice questions", "weak topics".
- List in "assumptions" only decisions you had to make yourself (empty list if none). Do not repeat
  the student facts, the dates or these rules as assumptions.

Output json exactly in this shape:
{
  "summary": "One sentence describing the plan.",
  "days": [
    {"date": "2026-11-18", "sessions": [
      {"subject": "Maths", "minutes": 60, "focus": "practice questions"},
      {"subject": "Physics", "minutes": 45, "focus": "review notes"}
    ]}
  ],
  "assumptions": []
}"""


def facts_json(slots: dict) -> str:
    """Only values go to the model, not provenance or UI notes."""
    return json.dumps({k: v["value"] for k, v in slots.items()}, ensure_ascii=False, sort_keys=True)


def build_extract_messages(today_iso: str, slots: dict, last_question: str | None, student_text: str) -> list[dict]:
    # Task stated first (system) and restated after the evidence (Lecture 10: position matters).
    user = (
        f"TODAY: {today_iso}\n"
        f"CURRENT UNDERSTANDING (for reference only): {facts_json(slots)}\n"
        f"ASSISTANT'S LAST QUESTION: {last_question or '(none - this is the first message)'}\n"
        f"STUDENT MESSAGE: {student_text}\n\n"
        "Extract the fields from the STUDENT MESSAGE and return the json object."
    )
    return [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}]


def build_plan_messages(today_iso: str, slots: dict, available: list[str],
                        repair_errors: list[str] | None = None) -> list[dict]:
    # The code works out the allowed dates (window and whole days off); the model is
    # bad at counting dates, so it is given the list instead (Lecture 08: context assembly).
    user = (
        f"TODAY: {today_iso}\n"
        f"AVAILABLE DATES: {json.dumps(available)}\n"
        f"STUDENT FACTS: {facts_json(slots)}\n\n"
        "Write the revision timetable and return the json object."
    )
    messages = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}]
    if repair_errors:
        messages.append({"role": "user", "content":
                         "Your previous plan broke these rules. Return a corrected json plan:\n- "
                         + "\n- ".join(repair_errors)})
    return messages
