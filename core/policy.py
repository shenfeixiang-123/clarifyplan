"""Ask policy: decides in code whether to ask, what to ask, or to act on an
assumption (act / ask / wait, after Horvitz 1999).

The model interprets what the student said; it does not decide how many
questions to ask. Keeping this rule in code makes it explicit, testable and
identical across Conditions A and B.
"""
from __future__ import annotations

from .slots import LABELS, REQUIRED, SLOT_ORDER

MAX_ASKS_PER_SLOT = 2          # after two tries, stop asking and assume or decline
DEFAULT_DAILY_HOURS = 2

ASSUMPTION_TEXT = {
    "daily_hours": f"You didn't give a daily study time, so I assumed {DEFAULT_DAILY_HOURS} hours a day.",
    "priority_subject": "No subject was marked as hardest, so I split time evenly.",
    "constraints": "I assumed you can study on any day.",
}


def _needed(slot: str, slots: dict) -> bool:
    """Is this slot worth a question? Only ask for information that changes the plan."""
    if slot == "priority_subject":
        subjects = slots["subjects"]["value"] or []
        return len(subjects) > 1          # nothing to prioritise with one subject
    return True


def next_question(slots: dict, asked: dict, total_asked: int, max_questions: int):
    """Return (slot, kind) to ask next, or None when the system should stop asking.

    kind is 'clarify' for a slot the student answered vaguely, otherwise 'ask'.
    """
    if total_asked >= max_questions:
        return None
    # 1) Repair first: a vague answer is clarified before moving on (Lecture 07).
    for slot in SLOT_ORDER:
        if slots[slot]["status"] == "ambiguous" and asked.get(slot, 0) < MAX_ASKS_PER_SLOT:
            return slot, "clarify"
    # 2) Then missing slots, in a fixed order.
    for slot in SLOT_ORDER:
        if slots[slot]["status"] != "missing" or not _needed(slot, slots):
            continue
        limit = 1 if slot == "constraints" else MAX_ASKS_PER_SLOT  # optional: ask once
        if asked.get(slot, 0) < limit:
            return slot, "ask"
    return None


def apply_defaults(slots: dict) -> None:
    """Once asking has stopped, fill optional slots with visible defaults."""
    if slots["daily_hours"]["value"] is None:
        slots["daily_hours"].update(value=DEFAULT_DAILY_HOURS, status="assumed", source="default", note=None)
    if slots["priority_subject"]["value"] is None and len(slots["subjects"]["value"] or []) > 1:
        slots["priority_subject"].update(value="none", status="assumed", source="default", note=None)
    if slots["constraints"]["value"] is None:
        slots["constraints"].update(value="none", status="assumed", source="default", note=None)


def assumptions(slots: dict) -> list[str]:
    """Assumptions are shown to the student before and with the plan."""
    return [ASSUMPTION_TEXT[s] for s in ASSUMPTION_TEXT if slots[s]["status"] == "assumed"]


def blockers(slots: dict) -> list[str]:
    """Required slots still unknown: the system declines to plan without them."""
    return [LABELS[s] for s in SLOT_ORDER if s in REQUIRED and slots[s]["value"] in (None, [], "")]
