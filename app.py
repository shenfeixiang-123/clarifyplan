"""ClarifyPlan - Streamlit interface.

Run:  streamlit run app.py
This file only renders a core.engine.Session and forwards actions to it.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import streamlit as st

from core.config import get_settings, today
from core.engine import CONDITIONS, Session, describe
from core.logger import SessionLogger
from core.slots import LABELS, SLOT_ORDER
from core.validator import DAY_NAMES, blocked_days

st.set_page_config(page_title="ClarifyPlan", page_icon="🗓️", layout="wide")
settings = get_settings()
SS = st.session_state

SOURCE_BADGE = {"said": "you said", "picked": "you picked", "edited": "you edited",
                "default": "assumed", "skipped": "you skipped", None: ""}


# ------------------------------------------------------------------ session
def new_session(condition: str) -> None:
    sid = uuid.uuid4().hex[:8]
    logger = SessionLogger(sid, settings.logs_dir)
    SS.session = Session(condition, today(), logger, max_questions=settings.max_questions,
                         seed=int(sid, 16) % 10_000)


if "session" not in SS:
    new_session("B")
session: Session = SS.session


def queue(*action) -> None:
    """Buttons only queue an action; it is processed below with visible feedback."""
    SS.queued = action


def dispatch(action, on_progress=None) -> None:
    kind = action[0]
    if kind == "text":
        session.handle_text(action[1])
    elif kind == "option":
        _, slot, value, label = action
        session.handle_option(slot, value, label)
    elif kind == "plan":
        session.generate_plan(on_progress=on_progress)
    elif kind == "skip":
        session.handle_skip()


def action_label(action) -> str | None:
    """What the student just did, echoed at once (feedback within ~0.1 s, Lecture 04)."""
    if action[0] == "text":
        return action[1]
    if action[0] == "option":
        return action[3]
    if action[0] == "skip":
        return "Not sure / skip"
    return None


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.caption(f"Model: DeepSeek `{settings.model}` · Today: {session.today:%a %d %b %Y}")
    if not settings.api_key:
        st.error("No DEEPSEEK_API_KEY found. Add it to .env and restart the app.")

    st.subheader("Condition")
    started = session.phase != "start"
    choice = st.radio("How questions are asked", list(CONDITIONS), index=list(CONDITIONS).index(session.condition),
                      format_func=lambda c: f"{c}: {CONDITIONS[c]}", disabled=started, horizontal=True)
    if choice != session.condition and not started:
        new_session(choice)
        st.rerun()
    if st.button("New conversation", use_container_width=True):
        new_session(session.condition)
        st.rerun()

    st.subheader("What I understood")
    for slot in SLOT_ORDER:
        sinfo = session.slots[slot]
        badge = SOURCE_BADGE.get(sinfo["source"], "")
        value = describe(slot, sinfo["value"])
        line = f"**{LABELS[slot]}:** {value}" + (f"  \n:grey[{badge}]" if badge and sinfo["value"] is not None else "")
        if sinfo["status"] == "ambiguous":
            line += f"  \n:orange[unclear: {sinfo['note'] or ''}]"
        elif sinfo["status"] == "skipped":
            line += "  \n:grey[you skipped]"
        st.markdown(line)

    with st.expander("Edit", expanded=False):
        with st.form("edit_form"):
            cur = session.slots
            exam = st.date_input("First exam date",
                                 value=date.fromisoformat(cur["exam_date"]["value"]) if cur["exam_date"]["value"] else None,
                                 min_value=session.today + timedelta(days=1))
            subjects = st.text_input("Subjects (comma-separated)", value=", ".join(cur["subjects"]["value"] or []))
            hours = st.number_input("Hours per day", min_value=0.25, max_value=16.0, step=0.25,
                                    value=float(cur["daily_hours"]["value"]) if cur["daily_hours"]["value"] else None)
            subject_list = [s.strip() for s in subjects.split(",") if s.strip()]
            prio_options = ["(not set)", "All about the same"] + subject_list
            prio_now = cur["priority_subject"]["value"]
            prio_index = 1 if prio_now == "none" else (prio_options.index(prio_now) if prio_now in prio_options else 0)
            prio = st.selectbox("Subject that needs most work", prio_options, index=prio_index)
            constraints = st.text_input("Constraints",
                                        value="" if cur["constraints"]["value"] in (None, "none") else cur["constraints"]["value"])
            if st.form_submit_button("Save changes"):
                errors = []
                edits = {"exam_date": exam.isoformat() if exam else None,
                         "subjects": subject_list or None,
                         "daily_hours": hours,
                         "priority_subject": None if prio == "(not set)" else ("none" if prio == "All about the same" else prio),
                         "constraints": constraints.strip() or None}
                for slot, value in edits.items():
                    if value is not None and value != cur[slot]["value"]:
                        problem = session.edit_slot(slot, value)
                        if problem:
                            errors.append(f"{LABELS[slot]}: {problem}")
                SS.flash = "; ".join(errors) if errors else None
                st.rerun()

    st.download_button("Download this session's log", mime="application/json",
                       data="\n".join(json.dumps(e, ensure_ascii=False) for e in session.log.events),
                       file_name=f"session-{session.log.session_id}.jsonl", use_container_width=True)


# --------------------------------------------------------------------- main
st.title("ClarifyPlan")
st.caption("I turn a short request into a day-by-day revision plan. I ask only for details that change the plan "
           "(exam date, subjects, study time). I can't see your timetable, grades or calendar, "
           "and I never save anything outside this session's log.")

if SS.get("flash"):
    st.warning(SS.pop("flash"))

if not session.messages:
    with st.chat_message("assistant"):
        st.markdown("What would you like help with? For example: *Help me revise next week.*")

for msg in session.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

# Condition B: options for the open question, plus an 'Other' answer.
pending = session.pending
if session.phase == "asking" and pending and pending.get("options"):
    opts = pending["options"]
    n = session.total_asked
    with st.container(border=True):
        # Callbacks read widget values from session state at click time, so text typed
        # just before clicking is not lost.
        def confirm_multi(slot=pending["slot"], n=n, options=opts["options"]):
            chosen = SS.get(f"multi_{n}") or []
            others = [s.strip() for s in (SS.get(f"multi_other_{n}") or "").split(",") if s.strip()]
            values = [v for l, v in options if l in chosen] + others
            if values:
                queue("option", slot, values, ", ".join(values))

        def send_other(n=n):
            text = (SS.get(f"other_{n}") or "").strip()
            if text:
                queue("text", text)

        if opts["multi"]:
            # All options visible at once (recognition rather than recall, Lecture 05).
            st.pills("Choose all that apply", [l for l, _ in opts["options"]], selection_mode="multi",
                     key=f"multi_{n}")
            st.text_input("Other (type your own, comma-separated)", key=f"multi_other_{n}")
            st.button("Confirm", key=f"multi_ok_{n}", type="primary", on_click=confirm_multi)
        else:
            cols = st.columns(4)
            for i, (label, value) in enumerate(opts["options"]):
                cols[i % 4].button(label, key=f"opt_{n}_{i}", use_container_width=True,
                                   on_click=queue, args=("option", pending["slot"], value, label))
            c1, c2 = st.columns([4, 1])
            c1.text_input("Other", key=f"other_{n}", placeholder="Other: type your own answer",
                          label_visibility="collapsed")
            c2.button("Send", key=f"other_ok_{n}", use_container_width=True, on_click=send_other)

# Both conditions: the student can decline any question (same control in A and B).
if session.phase == "asking" and pending:
    st.button("Not sure / skip this question", key=f"skip_{session.total_asked}",
              on_click=queue, args=("skip",))

if session.phase == "confirm" or (session.phase == "plan" and session.plan_stale):
    st.button("Make my plan" if session.phase == "confirm" else "Update my plan with the changes",
              type="primary", on_click=queue, args=("plan",))

# Plan view: built from the validated plan, with the checks shown beside it.
if session.phase == "plan" and session.plan:
    plan = session.plan
    st.subheader("Your revision plan" + ("  (out of date: details changed)" if session.plan_stale else ""))
    if plan.get("summary"):
        st.markdown(plan["summary"])
    for e in session.plan_errors:
        st.error(e)
    limit = float(session.slots["daily_hours"]["value"]) * 60
    for day in plan.get("days", []):
        sessions = [s for s in (day.get("sessions") or []) if isinstance(s.get("minutes"), (int, float))]
        if not sessions:
            continue                                   # days off are listed once below, not as empty days
        try:
            label = date.fromisoformat(day["date"]).strftime("%a %d %b")
        except (KeyError, ValueError):
            label = str(day.get("date"))
        total = sum(s["minutes"] for s in sessions)
        rows = "\n".join(f"| {s.get('subject', '')} | {int(s['minutes'])} | {s.get('focus', '')} |" for s in sessions)
        st.markdown(f"**{label}** · {int(total)} of {int(limit)} min\n\n"
                    f"| Subject | Minutes | Focus |\n|---|---:|---|\n{rows}")
    off = blocked_days(session.slots["constraints"]["value"])
    if off:
        st.caption("Days off (from your constraint): " + ", ".join(DAY_NAMES[i].title() for i in sorted(off)))
    assumed = session.assumptions + list(plan.get("assumptions") or [])
    if assumed:
        st.info("**Assumptions:**\n" + "\n".join(f"- {a}" for a in assumed))
    for w in session.plan_warnings:
        st.warning(w)
    st.caption("Checked by code: every day is before your exam, within your daily time and not a day off; "
               "every subject is included. Not checked: times of day and the quality of each session's focus.")

# Free text: always in A; in B only when no options are on screen (custom answers use 'Other').
text_disabled = session.condition == "B" and session.phase == "asking" and bool(pending and pending.get("options"))
placeholder = {"start": "Type your request…", "asking": "Type your answer…"}.get(session.phase, "Tell me if anything should change…")
typed = st.chat_input(placeholder, disabled=text_disabled)

action = SS.pop("queued", None) or (("text", typed) if typed else None)
if action:
    echo = action_label(action)
    if echo:
        with st.chat_message("user"):
            st.markdown(echo)
    with st.chat_message("assistant"):
        if action[0] == "plan":
            # Planning takes 15-30 s, beyond the ~10 s attention limit, so show each stage (Lecture 04).
            with st.status("Making your plan…", expanded=True) as status:
                dispatch(action, on_progress=status.write)
                status.update(label="Plan ready", state="complete")
        else:
            with st.spinner("Working on it…"):
                dispatch(action)
    st.rerun()
