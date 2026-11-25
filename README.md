# ClarifyPlan

Prose word count: 667 (code and setup commands excluded)

A revision-planning assistant that turns a vague request ("Help me revise next week") into a
day-by-day plan, asking only for details that change the plan. It compares two ways of asking:
**Condition A** open questions, and **Condition B** suggested options with a free "Other" answer.
Module: Intelligent Interactive Systems, A2. Submitted version: tag `v1.0-A2`.

## Project status
- **Works:** Conditions A and B; ask policy in code (clarify, ask, assume, decline); DeepSeek answer
  extraction and plan drafting, both checked in code with one repair; editable side panel and confirm
  step; "Why I ask" and "Not sure / skip" on every question; interaction log and per-condition summary script.
- **Simulated:** nothing.
- **Unfinished (Phase 3):** user study comparing A and B; calendar export; memory across sessions.

## Technology stack
- **Python 3.9+ and Streamlit:** interface; runs on the server, so the API key never reaches the browser.
- **DeepSeek API** via the `openai` SDK: two JSON-mode calls, one turns answers into facts, one drafts the plan.
- **pytest:** unit tests with a fake client (no network).
- **Undecided:** whether to deploy online for the Phase 3 study.

## Running or inspecting the work
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # add your own DEEPSEEK_API_KEY and DEEPSEEK_MODEL
streamlit run app.py
```
No API key is included; reviewers use their own.
```bash
python -m pytest -q                    # unit tests
python scripts/run_prompt_cases.py     # prompt cases (needs a key)
python scripts/summarise_logs.py       # per-condition table from logs/
```
Code: `core/engine.py` dialogue controller, `core/policy.py` ask policy, `core/llm.py` DeepSeek calls,
`core/prompts.py` prompts, `core/validator.py` checks, `core/logger.py` log.
Prompt versions and test scores: `docs/prompt_log.md`.

## Development record
Significant changes only. The repository was created after development, so they have no separate commits.

| Change | Why | Checked by |
|---|---|---|
| Removed record/replay mode; reviewers use their own key | Simpler to run and explain | Tests updated; app run live |
| Unanswered or vague answers are acknowledged; assumed values are marked | "A few hours" for the constraints question was passed over silently | Unit tests; manual re-run |
| "Next Tuesday" read as the coming Tuesday and shown at confirmation (prompt v0.3) | Asking about it was a false alarm (Lecture 04) | Prompt cases c05, c11, c12 |
| Days off checked by the days named (v0.5); part-day limits keep the day (v0.7) | "Saturdays" removed Sundays; "weekday mornings" blocked Monday–Friday | `blocked_days` tests; prompt case c17 |
| A correction that adds a subject keeps the others (v0.6) | "I also need to revise chemistry" replaced the list | Prompt cases c15, c16 |
| "Why I ask" and "Not sure / skip" on every question | Explain why a detail matters (Amershi et al., G11); a low-effort way out with a clear boundary | Unit tests; manual runs of A and B |
| Progress stages while planning; subject buttons in Condition B | 15–35 s waits with only a spinner (Lecture 04); hidden options weakened recognition (Lecture 05) | Manual re-test |
| Code gives the plan model the available dates; the 14-day limit is stated at confirmation | First plans used dates past the window and needed a repair | Unit tests; manual re-test passed first time |
| Smaller fixes (23 Nov): quarter-hour rounding, no plan request when every day is off, consistent priority subject, reason logged when a reply cannot be read | Found in live tests and code review | Unit tests (36 pass); prompt cases 25/25 |

## AI assistance
- **Claude:** generated the initial project skeleton (all modules, tests, docs templates) from my design: problem from my A1 review, two conditions, slots. I checked: I set the scope and the constraints before any code existed, and decided which of Claude's suggestions to keep. I then went through the result module by module, ran the app on my machine and changed what did not match my brief or the lecture criteria.
- **Claude, testing round (23 Nov, v0.7):** eviewed the code, ran both conditions with the live model, and drafted the fixes, tests and prompt changes listed for 2026-11-23. I checked: restarted the app and re-tested the weekday-mornings case myself (constraint kept as "no study on weekday mornings", weekdays planned, Geography given the most time); ran pytest (36 passed) and the prompt cases (25/25) on my own machine.
- **Claude, report drafting:** Built the framework of the report and assisted in generating the figures. I checked: decided the outline and what each section has to argue before drafting, and wrote and revised the text so that every claim traces back to the A1 review, the lecture criteria, the code or the logs. Checked every figure at full size against the current app, re-ran the diagram and storyboard scripts after the last code change, and corrected labels and screenshots that no longer matched.

## Additional files
- `docs/figures/`: system diagram, storyboards and their screenshots; `dev_evidence/` holds screenshots of
  problems found during development.
- `logs/`: created locally when the app runs (one JSONL file per session; not committed). The sidebar's
  *Download this session's log* button exports the current one.
