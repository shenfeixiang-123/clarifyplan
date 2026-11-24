"""Tests for the core logic. No network, no API key, no Streamlit needed.

Run:  python -m pytest -q
"""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from core import llm
from core.engine import Session
from core.logger import SessionLogger
from core.policy import next_question
from core.slots import empty_slots
from core.validator import clean_extraction, validate_plan

TODAY = date(2026, 11, 18)  # a Wednesday


class FakeClient:
    """Stands in for the OpenAI SDK client; returns queued JSON strings."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("FROZEN_DATE", TODAY.isoformat())
    yield tmp_path
    llm.set_client_factory(None)


def extraction(**slots):
    base = {s: {"value": None, "status": "missing", "evidence": None, "note": None}
            for s in ["exam_date", "subjects", "daily_hours", "priority_subject", "constraints"]}
    base.update(slots)
    return json.dumps({"slots": base})


def stated(value, evidence="x"):
    return {"value": value, "status": "stated", "evidence": evidence, "note": None}


# ------------------------------------------------------------------ llm
def test_empty_json_reply_is_retried(env, monkeypatch):
    client = FakeClient(["", '{"ok": true}'])
    llm.set_client_factory(lambda: client)
    data, meta = llm.call_json("extract", [{"role": "user", "content": "json"}])
    assert data == {"ok": True} and meta["attempts"] == 2


# ------------------------------------------------------------- validation
def test_past_exam_date_becomes_ambiguous():
    upd = clean_extraction(json.loads(extraction(exam_date=stated("2026-11-01"))), TODAY)
    assert upd["exam_date"]["status"] == "ambiguous"


def test_plan_checks_hours_window_and_coverage():
    slots = empty_slots()
    slots["exam_date"]["value"] = "2026-11-21"
    slots["subjects"]["value"] = ["Maths", "Physics"]
    slots["daily_hours"]["value"] = 2
    slots["priority_subject"]["value"] = "none"
    slots["constraints"]["value"] = "none"
    plan = {"days": [
        {"date": "2026-11-18", "sessions": [{"subject": "Maths", "minutes": 200}]},
        {"date": "2026-11-21", "sessions": [{"subject": "Maths", "minutes": 60}]},
    ]}
    errors, _ = validate_plan(plan, slots, TODAY)
    text = " ".join(errors)
    assert "200 minutes" in text and "outside the revision window" in text and "Physics" in text


def test_weekend_constraint_is_checked():
    slots = empty_slots()
    slots["exam_date"]["value"] = "2026-11-25"
    slots["subjects"]["value"] = ["Maths"]
    slots["daily_hours"]["value"] = 2
    slots["constraints"]["value"] = "No study on Saturdays or Sundays"
    plan = {"days": [{"date": "2026-11-21", "sessions": [{"subject": "Maths", "minutes": 60}]}]}
    errors, _ = validate_plan(plan, slots, TODAY)
    assert any("Saturday" in e and "day off" in e for e in errors)


# ---------------------------------------------------------------- policy
def test_policy_skips_priority_for_one_subject():
    slots = empty_slots()
    slots["exam_date"].update(value="2026-11-24", status="stated")
    slots["subjects"].update(value=["Maths"], status="stated")
    slots["daily_hours"].update(value=3, status="stated")
    assert next_question(slots, {}, 0, 5) == ("constraints", "ask")


def test_policy_clarifies_before_asking_new():
    slots = empty_slots()
    slots["daily_hours"]["status"] = "ambiguous"
    assert next_question(slots, {}, 0, 5) == ("daily_hours", "clarify")


# --------------------------------------------------------- whole sessions
def make_session(condition):
    return Session(condition, TODAY, SessionLogger("test", None, enabled=False), max_questions=5, seed=1)


def test_condition_b_flow_to_plan(env, monkeypatch):
    plan = {"summary": "s", "assumptions": [], "days": [
        {"date": "2026-11-18", "sessions": [{"subject": "Maths", "minutes": 60, "focus": "f"},
                                            {"subject": "Physics", "minutes": 90, "focus": "f"}]}]}
    client = FakeClient([extraction(), json.dumps(plan)])
    llm.set_client_factory(lambda: client)
    s = make_session("B")
    s.handle_text("Help me revise next week")
    assert s.pending["slot"] == "exam_date"
    s.handle_option("exam_date", "2026-11-20", "Fri 20 Nov")
    assert s.pending["slot"] == "subjects"
    s.handle_option("subjects", ["Maths", "Physics"], "Maths, Physics")
    s.handle_option("daily_hours", 3, "3 h")
    s.handle_option("priority_subject", "Physics", "Physics")
    s.handle_option("constraints", "none", "No constraints")
    assert s.phase == "confirm"
    s.generate_plan()
    assert s.phase == "plan" and s.plan_errors == []
    assert len(client.calls) == 2   # option answers never call the model


def test_condition_a_vague_answer_is_clarified(env, monkeypatch):
    client = FakeClient([
        extraction(exam_date=stated("2026-11-24"), subjects=stated(["Maths"])),
        extraction(daily_hours={"value": None, "status": "ambiguous", "evidence": "a few hours", "note": "vague"}),
    ])
    llm.set_client_factory(lambda: client)
    s = make_session("A")
    s.handle_text("Maths exam next Tuesday, help")
    assert s.pending["slot"] == "daily_hours"
    s.handle_text("a few hours")
    assert s.pending["kind"] == "clarify" and "a few hours" in s.pending["question"]


def test_missing_required_fact_blocks_plan(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction()] * 6))
    s = Session("A", TODAY, SessionLogger("t", None, enabled=False), max_questions=2)
    s.handle_text("help")
    s.handle_text("dunno")
    s.handle_text("dunno")
    assert s.phase == "blocked"


def test_unanswered_question_is_acknowledged(env, monkeypatch):
    # Asked about constraints, the student answers something else: say so, then assume visibly.
    client = FakeClient([
        extraction(exam_date=stated("2026-11-24"), subjects=stated(["Maths"]), daily_hours=stated(3)),
        extraction(daily_hours={"value": None, "status": "ambiguous", "evidence": "a few hours", "note": "vague"}),
    ])
    llm.set_client_factory(lambda: client)
    s = make_session("A")
    s.handle_text("Maths exam on 24 Nov, 3 hours a day")
    assert s.pending["slot"] == "constraints"
    s.handle_text("a few hours")
    texts = [m["text"] for m in s.messages]
    notice = next(t for t in texts if "doesn't seem to answer" in t)
    assert "times you can't study" in notice
    assert 'You mentioned "a few hours"' in notice and "3 h" in notice
    assert s.slots["daily_hours"]["value"] == 3          # known value not overwritten by a vague mention
    assert s.phase == "confirm" and "*(assumed)*" in texts[-1]


def test_clarify_shows_candidate_dates(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction(
        exam_date={"value": None, "status": "ambiguous", "evidence": "next Tuesday",
                   "note": "could be Tue 24 Nov or Tue 1 Dec"},
        subjects=stated(["Maths"]))]))
    s = make_session("A")
    s.handle_text("Maths exam next Tuesday")
    assert s.pending["kind"] == "clarify"
    assert "could be Tue 24 Nov or Tue 1 Dec" in s.pending["question"]


# ------------------------------------------------- days off (found in manual test)
from core.validator import blocked_days  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("I work at a cafe on Saturdays", {5}),                 # Saturday only, not the whole weekend
    ("No study on Saturdays or Sundays", {5, 6}),
    ("no study at weekends", {5, 6}),
    ("only weekday evenings", {5, 6}),                      # 'only' names the days they CAN study
    ("only weekends", {0, 1, 2, 3, 4}),
    ("Can only study in the evenings", set()),              # time of day: not checked by code
    ("none", set()),
])
def test_blocked_days(text, expected):
    assert blocked_days(text) == expected


def test_saturday_constraint_allows_sunday():
    slots = empty_slots()
    slots["exam_date"]["value"] = "2026-11-25"
    slots["subjects"]["value"] = ["Maths"]
    slots["daily_hours"]["value"] = 2
    slots["constraints"]["value"] = "no study on Saturdays"
    plan = {"days": [{"date": "2026-11-21", "sessions": [{"subject": "Maths", "minutes": 60}]},   # Sat
                     {"date": "2026-11-22", "sessions": [{"subject": "Maths", "minutes": 60}]}]}  # Sun
    errors, _ = validate_plan(plan, slots, TODAY)
    assert len(errors) == 1 and "2026-11-21" in errors[0]


def test_priority_subject_is_capitalised():
    upd = clean_extraction(json.loads(extraction(priority_subject=stated("chemistry"))), TODAY)
    assert upd["priority_subject"]["value"] == "Chemistry"


def test_plan_reports_progress_and_repairs(env, monkeypatch):
    bad = {"days": [{"date": "2026-11-21", "sessions": [{"subject": "Maths", "minutes": 60}]}]}   # Saturday
    good = {"days": [{"date": "2026-11-20", "sessions": [{"subject": "Maths", "minutes": 60}]}]}
    client = FakeClient([json.dumps(bad), json.dumps(good)])
    llm.set_client_factory(lambda: client)
    s = make_session("B")
    s.slots["exam_date"].update(value="2026-11-24", status="stated")
    s.slots["subjects"].update(value=["Maths"], status="stated")
    s.slots["daily_hours"].update(value=2, status="stated")
    s.slots["constraints"].update(value="no study at weekends", status="stated")
    s.phase = "confirm"
    seen = []
    s.generate_plan(on_progress=seen.append)
    assert s.plan == good and s.plan_errors == []
    assert any("problem" in m for m in seen) and len(client.calls) == 2


def test_long_or_repeating_note_is_not_shown(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction(
        subjects=stated(["Maths"]), exam_date=stated("2026-11-24"),
        daily_hours={"value": None, "status": "ambiguous", "evidence": "a few hours",
                     "note": 'you said "a few hours" which is unclear'})]))
    s = make_session("A")
    s.handle_text("maths on 24 Nov, a few hours")
    assert s.pending["question"].startswith('You said "a few hours". ')


# ------------------------------------------------ why-text, skip, log summary
def test_question_shows_why(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction()]))
    s = make_session("A")
    s.handle_text("help me revise")
    assert s.pending["slot"] == "exam_date"
    assert "Why I ask:" in s.messages[-1]["text"] and s.pending["why"]


def test_skip_optional_uses_visible_default(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([
        extraction(exam_date=stated("2026-11-24"), subjects=stated(["Maths"]))]))
    s = make_session("B")
    s.handle_text("maths exam on 24 Nov")
    assert s.pending["slot"] == "daily_hours"
    s.handle_skip()
    assert s.pending["slot"] == "constraints"            # not asked again
    s.handle_skip()
    assert s.phase == "confirm"
    assert s.slots["daily_hours"]["status"] == "assumed" and s.slots["daily_hours"]["value"] == 2
    assert any("2 hours" in a for a in s.assumptions)


def test_skip_required_blocks_plan(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction(subjects=stated(["Maths"]))]))
    s = make_session("B")
    s.handle_text("maths")
    assert s.pending["slot"] == "exam_date"
    s.handle_skip()
    assert any("can't make a plan without" in m["text"] for m in s.messages)
    s.handle_skip()          # daily hours
    s.handle_skip()          # constraints
    assert s.phase == "blocked"


def test_summarise_logs(tmp_path, env, monkeypatch):
    from scripts.summarise_logs import load_sessions, summarise, table
    logs = tmp_path / "pilot"
    llm.set_client_factory(lambda: FakeClient([extraction(), extraction(subjects=stated(["Maths"]))]))
    a = Session("A", TODAY, SessionLogger("aaaa", logs), max_questions=5)
    a.handle_text("help")
    a.handle_text("maths")
    b = Session("B", TODAY, SessionLogger("bbbb", logs), max_questions=5)
    llm.set_client_factory(lambda: FakeClient([extraction()]))
    b.handle_text("help")
    b.handle_option("exam_date", "2026-11-24", "Tue 24 Nov")
    b.handle_skip()
    by_cond = summarise(load_sessions(logs))
    assert set(by_cond) == {"A", "B"}
    assert sum(by_cond["B"]["skips"]) == 1 and sum(by_cond["B"]["option_answers"]) == 1
    assert sum(by_cond["A"]["typed_answers"]) == 1
    assert "| Sessions |" in table(by_cond)


# ------------------------------------------------ v0.7 (found in testing round 3)
def test_quarter_hours_do_not_round_to_zero():
    upd = clean_extraction(json.loads(extraction(daily_hours=stated(0.25, "15 minutes a day"))), TODAY)
    assert upd["daily_hours"]["value"] == 0.25


@pytest.mark.parametrize("text, expected", [
    ("no study on weekday mornings", set()),               # part of the day: no whole day off
    ("I work Saturday afternoons", set()),
    ("I work Saturdays", {5}),
])
def test_part_day_constraints_block_no_whole_day(text, expected):
    assert blocked_days(text) == expected


def test_no_available_day_blocks_before_planning(env, monkeypatch):
    # Exam on Saturday 21 Nov; today Wed 18 Nov; no study on weekdays -> Wed, Thu, Fri all off.
    client = FakeClient([extraction(exam_date=stated("2026-11-21"), subjects=stated(["Maths"]),
                                    daily_hours=stated(2), constraints=stated("no study on weekdays"))])
    llm.set_client_factory(lambda: client)
    s = make_session("A")
    s.handle_text("maths exam Saturday, 2 hours a day, I can't study on weekdays")
    assert s.phase == "blocked" and "no day to plan" in s.messages[-1]["text"]
    assert len(client.calls) == 1                         # the plan model is never called


def test_priority_not_in_subjects_is_added(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([
        extraction(exam_date=stated("2026-11-24"), subjects=stated(["Maths", "Physics"]))]))
    s = make_session("B")
    s.handle_text("maths and physics, exam on 24 Nov")
    s.handle_option("daily_hours", 2, "2 h")
    assert s.pending["slot"] == "priority_subject"
    s.handle_option("priority_subject", "Chemistry", "Chemistry")      # typed via Other
    assert s.slots["subjects"]["value"] == ["Maths", "Physics", "Chemistry"]
    assert any("added Chemistry" in m["text"] for m in s.messages)


def test_priority_cleared_when_subject_removed(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction(subjects=stated(["Maths"]))]))
    s = make_session("A")
    s.slots["exam_date"].update(value="2026-11-24", status="stated")
    s.slots["subjects"].update(value=["Maths", "Physics"], status="stated")
    s.slots["priority_subject"].update(value="Physics", status="stated")
    s.phase = "confirm"
    s.handle_text("actually only maths")
    assert s.slots["priority_subject"]["value"] is None
    assert any("Physics is no longer one of your subjects" in m["text"] for m in s.messages)


def test_long_horizon_is_explained(env, monkeypatch):
    llm.set_client_factory(lambda: FakeClient([extraction(
        exam_date=stated("2026-12-20"), subjects=stated(["Maths"]), daily_hours=stated(2),
        constraints=stated("none"))]))
    s = make_session("A")
    s.handle_text("maths exam on 20 Dec, 2 hours a day, no constraints")
    assert s.phase == "confirm" and "covers the next 14 days" in s.messages[-1]["text"]


def test_plan_prompt_lists_only_available_dates(env, monkeypatch):
    plan = {"days": [{"date": "2026-11-20", "sessions": [{"subject": "Maths", "minutes": 60}]}]}
    client = FakeClient([json.dumps(plan)])
    llm.set_client_factory(lambda: client)
    s = make_session("A")
    s.slots["exam_date"].update(value="2026-11-24", status="stated")     # Tue: window Wed 18 - Mon 23
    s.slots["subjects"].update(value=["Maths"], status="stated")
    s.slots["daily_hours"].update(value=2, status="stated")
    s.slots["constraints"].update(value="no study on Saturdays", status="stated")
    s.phase = "confirm"
    s.generate_plan()
    line = next(l for l in client.calls[0]["messages"][1]["content"].splitlines() if l.startswith("AVAILABLE DATES"))
    assert '"2026-11-20"' in line and '"2026-11-23"' in line
    assert "2026-11-21" not in line and "2026-11-24" not in line   # Saturday and exam day left out


def test_failed_json_reports_cut_off_reply(env, monkeypatch):
    class Cut(FakeClient):
        def _create(self, **kwargs):
            r = super()._create(**kwargs)
            r.choices[0].finish_reason = "length"
            return r
    llm.set_client_factory(lambda: Cut(['{"days": [', '{"days": [']))
    with pytest.raises(llm.LLMError) as err:
        llm.call_json("plan", [{"role": "user", "content": "json"}])
    assert "cut off" in str(err.value) and err.value.detail["finish_reasons"] == ["length", "length"]
