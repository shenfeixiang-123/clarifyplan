"""Dialogue controller: one Session per student conversation.

Flow:  start -> asking -> confirm -> plan
                    \\-> blocked (a required fact is still unknown)

The Streamlit app only renders a Session and forwards user actions to it,
so all behaviour here can be tested without a browser.
"""
from __future__ import annotations

import random
import time
from datetime import date

from . import policy
from .llm import LLMError, call_json
from .prompts import PROMPT_VERSION, build_extract_messages, build_plan_messages
from .slots import LABELS, REQUIRED, WHY, empty_slots, options_for, question_text
from .validator import PLAN_HORIZON_DAYS, available_days, clean_extraction, clean_value, plan_window, validate_plan

CONDITIONS = {"A": "Open questions", "B": "Options + Other"}
TOPICS = {
    "exam_date": "your exam date",
    "subjects": "your subjects",
    "daily_hours": "your daily study time",
    "priority_subject": "which subject needs most work",
    "constraints": "times you can't study",
}


def describe(slot: str, value) -> str:
    """Human-readable value for the state panel and confirmations."""
    if value is None:
        return "—"
    if slot == "exam_date":
        return date.fromisoformat(value).strftime("%a %d %b %Y")
    if slot == "subjects":
        return ", ".join(value)
    if slot == "daily_hours":
        return f"{value:g} h"
    if value == "none":
        return "all about the same" if slot == "priority_subject" else "none"
    return str(value)


class Session:
    def __init__(self, condition: str, today: date, logger, max_questions: int = 5, seed: int = 0):
        assert condition in CONDITIONS
        self.condition = condition
        self.today = today
        self.log = logger
        self.max_questions = max_questions
        self.rng = random.Random(seed)
        self.slots = empty_slots()
        self.messages: list[dict] = []        # {"role": "user"|"assistant", "text": str, "meta": {...}}
        self.phase = "start"
        self.pending: dict | None = None      # the question currently on screen
        self.asked: dict[str, int] = {}
        self.total_asked = 0
        self.last_question: str | None = None
        self.plan: dict | None = None
        self.plan_errors: list[str] = []
        self.plan_warnings: list[str] = []
        self.plan_stale = False
        self._reconciled_subjects = False
        self.log.log("session_start", condition=condition, today=today.isoformat(),
                     prompt_version=PROMPT_VERSION, max_questions=max_questions)

    # ------------------------------------------------------------------ helpers
    def _say(self, text: str, **meta) -> None:
        self.messages.append({"role": "assistant", "text": text, "meta": meta})

    def _user(self, text: str, **meta) -> None:
        self.messages.append({"role": "user", "text": text, "meta": meta})

    def _latency_ms(self) -> int | None:
        if self.pending is None:
            return None
        return int((time.time() - self.pending["shown_at"]) * 1000)

    def _set(self, slot: str, value, status: str, source: str, evidence=None, note=None) -> None:
        self.slots[slot].update(value=value, status=status, source=source, evidence=evidence, note=note)

    @property
    def assumptions(self) -> list[str]:
        return policy.assumptions(self.slots)

    # ------------------------------------------------------------ user actions
    def handle_text(self, text: str) -> None:
        """Free text: the first request, an open answer (A), an 'Other' answer (B),
        or a correction after the plan."""
        text = text.strip()
        if not text:
            return
        latency = self._latency_ms()
        slot = self.pending["slot"] if self.pending else None
        self._user(text, via="text")
        self.log.log("answer_text", phase=self.phase, slot=slot, latency_ms=latency, chars=len(text))
        updates = self._extract(text)
        if updates is None:
            return                                  # error already explained; question stays open
        changed, kept = self._apply(updates)
        self.log.log("slots_updated", slots=changed, kept=kept,
                     statuses={s: self.slots[s]["status"] for s in changed})
        notes = self._reconcile_priority(changed)
        if self._reconciled_subjects:
            # The subject list was just extended on purpose; a "kept from earlier" note would contradict it.
            kept = [(k, e) for k, e in kept if k != "subjects"]
        if self.phase == "asking" and slot and slot not in changed:
            # The answer did not address the open question: say so instead of moving on silently.
            notes.append(f"That doesn't seem to answer my question about {TOPICS[slot]}.")
            self.log.log("question_unanswered", slot=slot)
        for k, evidence in kept:
            # A vague mention of something already known: keep the value, but say so.
            notes.append(f'You mentioned "{evidence}", so I kept {LABELS[k].lower()} as '
                         f"{describe(k, self.slots[k]['value'])} from earlier. Edit it on the left if that changed.")
        if notes:
            self._say(" ".join(notes), kind="not_understood")
        if self.phase == "plan" and changed:
            self.plan_stale = True
        self._advance()

    def handle_option(self, slot: str, value, label: str) -> None:
        """Condition B: the student picked one of the offered options."""
        latency = self._latency_ms()
        clean, problem = clean_value(slot, value, self.today)
        self._user(label, via="option")
        self.log.log("answer_option", slot=slot, value=value, latency_ms=latency)
        if problem:
            self._say(f"That option didn't work ({problem}). Please choose another or type your answer.")
            return
        self._set(slot, clean, "stated", source="picked", evidence=label)
        notes = self._reconcile_priority([slot])
        if notes:
            self._say(" ".join(notes), kind="reconciled")
        self._advance()

    def handle_skip(self) -> None:
        """'Not sure / skip': the student declines the open question. The system does
        not ask it again; an optional detail gets a visible default, a required one
        means no plan until it is given (the autonomy boundary is stated, not hidden)."""
        if self.phase != "asking" or not self.pending:
            return
        slot = self.pending["slot"]
        latency = self._latency_ms()
        self._user("Not sure / skip", via="skip")
        self.log.log("answer_skip", slot=slot, latency_ms=latency)
        self._set(slot, None, "skipped", source="skipped")
        if slot in REQUIRED:
            self._say(f"OK. I can't make a plan without your {LABELS[slot].lower()}, so I'll need it "
                      "before planning. You can add it on the left at any time.", kind="skip_ack")
        else:
            self._say("OK, I'll use a default for that and show it before making the plan.", kind="skip_ack")
        self._advance()

    def edit_slot(self, slot: str, value) -> str | None:
        """Direct edit in the state panel. Returns an error message or None."""
        clean, problem = clean_value(slot, value, self.today)
        if problem:
            return problem
        old = self.slots[slot]["value"]
        if clean == old:
            return None
        self._set(slot, clean, "stated", source="edited")
        self.log.log("slot_edited", slot=slot, old=old, new=clean, phase=self.phase)
        if self.phase == "plan":
            self.plan_stale = True
        if self.phase == "start":
            return None
        notes = self._reconcile_priority([slot])
        self._say(" ".join([f"Updated {LABELS[slot].lower()} to {describe(slot, clean)}."] + notes), kind="edit_ack")
        # Re-plan the conversation only if the edit answers the open question or
        # changes an already confirmed summary; otherwise keep the current question.
        if self.phase != "asking" or (self.pending and self.pending["slot"] == slot):
            self._advance()
        return None

    def generate_plan(self, on_progress=None) -> None:
        """on_progress(text) is called at each stage, so the UI can show what is
        happening during a slow call (feedback beyond ~10 s, Lecture 04)."""
        if self.phase not in ("confirm", "plan"):
            return
        progress = on_progress or (lambda text: None)
        errors: list[str] = []
        warnings: list[str] = []
        data = None
        for attempt in (1, 2):                     # one repair attempt with the code's error list
            if attempt == 1:
                progress("Writing your timetable with DeepSeek (usually 15–30 seconds)…")
            else:
                progress(f"Found {len(errors)} problem(s), e.g. {errors[0]} Asking for a corrected timetable…")
            available = [d.isoformat() for d in available_days(self.slots, self.today)]
            messages = build_plan_messages(self.today.isoformat(), self.slots, available,
                                           errors if attempt == 2 else None)
            try:
                data, meta = call_json("plan", messages, max_tokens=3000)
            except LLMError as exc:
                self._say(f"I couldn't make the plan just now: {exc} Press the button to try again.")
                self.log.log("llm_error", purpose="plan", error=str(exc), **exc.detail)
                return
            self.log.log("llm_call", purpose="plan", attempt=attempt, **meta)
            progress("Checking every day against your exam date, daily time and days off…")
            errors, warnings = validate_plan(data, self.slots, self.today)
            self.log.log("plan_checked", attempt=attempt, errors=errors, warnings=warnings)
            if not errors:
                break
        self.plan, self.plan_errors, self.plan_warnings = data, errors, warnings
        self.plan_stale = False
        self.phase = "plan"
        if errors:
            self._say("I couldn't produce a plan that passes every check. The problems are marked below; "
                      "you can change your details and try again.")
        else:
            self._say("Here is your plan. Every day was checked against your exam date and daily time.")

    # ------------------------------------------------------------- internals
    def _extract(self, text: str) -> dict | None:
        messages = build_extract_messages(self.today.isoformat(), self.slots, self.last_question, text)
        try:
            data, meta = call_json("extract", messages)
        except LLMError as exc:
            hint = " or pick an option" if self.condition == "B" and self.pending else ""
            self._say(f"I couldn't process that just now ({exc}). Please try again{hint}.")
            self.log.log("llm_error", purpose="extract", error=str(exc), **exc.detail)
            return None
        self.log.log("llm_call", purpose="extract", **meta)
        return clean_extraction(data, self.today)

    def _apply(self, updates: dict) -> tuple[list[str], list[tuple[str, str]]]:
        """Returns (changed slots, [(slot, evidence)] for vague mentions of known values that were kept)."""
        changed, kept = [], []
        asking_about = self.pending["slot"] if self.pending else None
        for slot, upd in updates.items():
            current = self.slots[slot]
            if upd["status"] == "ambiguous":
                # A vague mention never overwrites a known value, unless it answers the open question.
                if current["value"] is not None and slot != asking_about:
                    if upd["evidence"]:
                        kept.append((slot, upd["evidence"]))
                    continue
                self._set(slot, None, "ambiguous", "said", upd["evidence"], upd["note"])
            else:
                self._set(slot, upd["value"], "stated", "said", upd["evidence"])
            changed.append(slot)
        return changed, kept

    def _reconcile_priority(self, changed: list[str]) -> list[str]:
        """Keep 'subject that needs most work' consistent with the subject list.

        A priority that is not one of the subjects is either a new subject (the student
        just named it) or left over from a list that changed (it is cleared, not kept silently).
        """
        self._reconciled_subjects = False
        priority, subjects = self.slots["priority_subject"]["value"], self.slots["subjects"]["value"]
        if not priority or priority == "none" or not subjects:
            return []
        if priority.lower() in {s.lower() for s in subjects}:
            return []
        if "priority_subject" in changed:
            self.slots["subjects"]["value"] = subjects + [priority]
            self._reconciled_subjects = True
            self.log.log("priority_reconciled", action="added_to_subjects", subject=priority)
            return [f"I added {priority} to your subjects, since it needs the most work."]
        self._set("priority_subject", None, "missing", source=None)
        self.log.log("priority_reconciled", action="cleared", subject=priority)
        return [f"{priority} is no longer one of your subjects, so I cleared which subject needs most work."]

    def _advance(self) -> None:
        nxt = policy.next_question(self.slots, self.asked, self.total_asked, self.max_questions)
        if nxt:
            slot, kind = nxt
            self.asked[slot] = self.asked.get(slot, 0) + 1
            self.total_asked += 1
            text = question_text(slot, kind)
            evidence, note = self.slots[slot]["evidence"], self.slots[slot]["note"]
            if note and (len(note) > 60 or (evidence and evidence.lower() in note.lower())):
                note = None                         # too long, or just repeats the quote
            if kind == "clarify" and evidence:
                # Clarify by showing what was heard and the readings the system has (Lecture 07).
                text = f'You said "{evidence}"' + (f" ({note})" if note else "") + f". {text}"
            opts = options_for(slot, self.today, self.slots, self.rng) if self.condition == "B" else None
            self.pending = {"slot": slot, "kind": kind, "question": text, "why": WHY[slot], "options": opts,
                            "shown_at": time.time()}
            self.last_question = text
            self.phase = "asking"
            self._say(f"{text}\n\n*Why I ask: {WHY[slot]}*", kind="question", slot=slot)
            self.log.log("question_shown", slot=slot, kind=kind, n=self.total_asked,
                         n_options=len(opts["options"]) if opts else 0)
            return

        self.pending = None
        policy.apply_defaults(self.slots)
        missing = policy.blockers(self.slots)
        if missing:
            self.phase = "blocked"
            self._say("I can't make a plan without: " + ", ".join(missing).lower()
                      + ". Tell me, or fill it in on the left.", kind="decline")
            self.log.log("blocked", missing=missing)
            return
        if not available_days(self.slots, self.today):
            first, last = plan_window(self.slots["exam_date"]["value"], self.today)
            span = (describe("exam_date", first.isoformat()) if first == last else
                    f"{describe('exam_date', first.isoformat())} to {describe('exam_date', last.isoformat())}")
            self.phase = "blocked"
            self._say(f"Every day from {span} is a day off under \"{self.slots['constraints']['value']}\", "
                      "so there is no day to plan. Change your exam date or constraints on the left, or tell me.",
                      kind="decline")
            self.log.log("blocked", missing=[], reason="no_available_days")
            return
        self.phase = "confirm"
        lines = [f"- **{LABELS[s]}:** {describe(s, self.slots[s]['value'])}"
                 + (" *(assumed)*" if self.slots[s]["status"] == "assumed" else "")
                 for s in self.slots if self.slots[s]["value"] is not None]
        text = "Here is what I understood:\n" + "\n".join(lines)
        days_left = (date.fromisoformat(self.slots["exam_date"]["value"]) - self.today).days
        if days_left > PLAN_HORIZON_DAYS:
            text += (f"\n\nYour exam is {days_left} days away. The plan covers the next "
                     f"{PLAN_HORIZON_DAYS} days; make a new one after that.")
        if self.assumptions:
            text += "\n\n**Assumptions:**\n" + "\n".join(f"- {a}" for a in self.assumptions)
        text += "\n\nIf anything is wrong, edit it on the left or tell me. Otherwise press **Make my plan**."
        self._say(text, kind="confirm")
        self.log.log("confirm_shown", assumptions=self.assumptions, total_asked=self.total_asked)
