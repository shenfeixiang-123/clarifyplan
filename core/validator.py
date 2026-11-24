"""Checks in code on everything the model returns.

A JSON schema guarantees shape, not truth (Lecture 09); reliability is a
property of the system, not the model (Lecture 08). Nothing the model says is
shown as fact or acted on without passing through here.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .slots import SLOT_ORDER

PLAN_HORIZON_DAYS = 14
MINUTES_TOLERANCE = 10

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS, WEEKEND = {0, 1, 2, 3, 4}, {5, 6}
# A day named together with a time of day ("Saturday mornings") is only partly off.
TIME_OF_DAY = re.compile(r"\b(mornings?|afternoons?|evenings?|nights?|lunch|before|after|until|"
                         r"\d{1,2}\s*(am|pm)|\d{1,2}:\d{2})\b")


def blocked_days(constraint: str | None) -> set[int]:
    """Weekdays (0 = Monday) on which the student can't study, read from the constraint text.

    The constraint answers "Is there any time you can't study?", so a day that is
    named is a day off ("I work on Saturdays" -> Saturday only). With "only", the
    named days are the ones they CAN study ("weekends only" -> Monday-Friday off).
    Times of day ("evenings only") give no blocked days; they are not checked by code.
    A day off for part of the day ("no study on weekday mornings") blocks no whole day.
    """
    if not constraint or constraint == "none":
        return set()
    text = constraint.lower()
    named = {i for i, d in enumerate(DAY_NAMES) if d in text}
    if "weekend" in text:
        named |= WEEKEND
    if "weekday" in text:
        named |= WEEKDAYS
    if not named:
        return set()
    if "only" in text:
        return set(range(7)) - named
    if TIME_OF_DAY.search(text):
        return set()
    return named


def plan_window(exam_iso: str, today: date) -> tuple[date, date]:
    """First and last day the plan may use: today up to the day before the exam, at most 14 days."""
    exam = date.fromisoformat(exam_iso)
    return today, min(exam - timedelta(days=1), today + timedelta(days=PLAN_HORIZON_DAYS - 1))


def available_days(slots: dict, today: date) -> list[date]:
    """Days in the window that are not a day off. Empty means no plan is possible."""
    first, last = plan_window(slots["exam_date"]["value"], today)
    off = blocked_days(slots["constraints"]["value"])
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return [d for d in days if d.weekday() not in off]


def clean_value(slot: str, value, today: date):
    """Return (clean_value, problem). problem is None if the value is usable."""
    if slot == "exam_date":
        try:
            d = date.fromisoformat(str(value))
        except ValueError:
            return None, "not a valid date"
        if d <= today:
            return None, "that date is not in the future"
        if d > today + timedelta(days=365):
            return None, "that date is more than a year away"
        return d.isoformat(), None
    if slot == "subjects":
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list):
            return None, "not a list of subjects"
        seen, out = set(), []
        for item in items:
            name = str(item).strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name[:1].upper() + name[1:])
        return (out, None) if out else (None, "no subject names")
    if slot == "daily_hours":
        try:
            hours = float(value)
        except (TypeError, ValueError):
            return None, "not a number of hours"
        if not 0 < hours <= 16:
            return None, "hours per day must be between 0 and 16"
        # Quarter hours, so "15 minutes a day" stays 0.25 h instead of rounding to 0.
        return max(round(hours * 4) / 4, 0.25), None
    if slot == "priority_subject":
        text = str(value).strip()
        if not text:
            return None, "empty"
        return (text if text == "none" else text[:1].upper() + text[1:]), None
    if slot == "constraints":
        text = str(value).strip()
        return (text, None) if text else (None, "empty")
    return None, "unknown field"


def clean_extraction(data: dict, today: date) -> dict:
    """Turn the model's extraction into slot updates the session can trust.

    A value that fails a check is downgraded to 'ambiguous', so the ask policy
    asks about it instead of the plan silently using it.
    """
    raw = data.get("slots", {}) if isinstance(data, dict) else {}
    updates = {}
    for slot in SLOT_ORDER:
        item = raw.get(slot) or {}
        status = item.get("status")
        if status not in ("stated", "ambiguous"):
            continue
        evidence = item.get("evidence")
        if status == "ambiguous" or item.get("value") is None:
            updates[slot] = {"value": None, "status": "ambiguous", "evidence": evidence,
                             "note": item.get("note") or "too vague to use"}
            continue
        value, problem = clean_value(slot, item["value"], today)
        if problem:
            updates[slot] = {"value": None, "status": "ambiguous", "evidence": evidence, "note": problem}
        else:
            updates[slot] = {"value": value, "status": "stated", "evidence": evidence, "note": None}
    return updates


def validate_plan(plan: dict, slots: dict, today: date) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors trigger one repair request to the model;
    warnings are shown to the student next to the plan."""
    errors: list[str] = []
    warnings: list[str] = []
    days = plan.get("days") if isinstance(plan, dict) else None
    if not isinstance(days, list) or not days:
        return ["The plan has no days."], warnings

    _, last_day = plan_window(slots["exam_date"]["value"], today)
    limit = float(slots["daily_hours"]["value"]) * 60 + MINUTES_TOLERANCE
    subjects = slots["subjects"]["value"] or []
    minutes_by_subject = {s.lower(): 0 for s in subjects}

    for day in days:
        try:
            d = date.fromisoformat(str(day.get("date")))
        except ValueError:
            errors.append(f"'{day.get('date')}' is not a valid date.")
            continue
        if d < today or d > last_day:
            errors.append(f"{d.isoformat()} is outside the revision window "
                          f"({today.isoformat()} to {last_day.isoformat()}).")
        total = 0
        for session in day.get("sessions") or []:
            minutes = session.get("minutes")
            if not isinstance(minutes, (int, float)) or minutes <= 0:
                errors.append(f"{d.isoformat()}: a session has no valid minutes.")
                continue
            total += minutes
            name = str(session.get("subject", "")).lower()
            if name in minutes_by_subject:
                minutes_by_subject[name] += minutes
            else:
                warnings.append(f"{d.isoformat()}: '{session.get('subject')}' was not one of your subjects.")
        if total > limit:
            errors.append(f"{d.isoformat()} has {int(total)} minutes, more than "
                          f"{slots['daily_hours']['value']} hours.")

    missing = [s for s in subjects if minutes_by_subject[s.lower()] == 0]
    if missing:
        errors.append("These subjects never appear: " + ", ".join(missing) + ".")

    priority = slots["priority_subject"]["value"]
    if priority and priority != "none" and priority.lower() in minutes_by_subject:
        top = max(minutes_by_subject.values())
        if minutes_by_subject[priority.lower()] < top:
            warnings.append(f"{priority} does not get the most time, although you marked it as hardest.")

    constraints = slots["constraints"]["value"]
    off = blocked_days(constraints)
    if off:
        for day in days:
            try:
                d = date.fromisoformat(str(day.get("date")))
            except ValueError:
                continue
            if d.weekday() in off and day.get("sessions"):
                errors.append(f"{d.isoformat()} is a {DAY_NAMES[d.weekday()].title()}, "
                              f"which should be a day off.")
    elif constraints and constraints != "none":
        warnings.append(f"Your constraint ('{constraints}') was given to the model but is not checked by code.")
    return errors, warnings
