# ClarifyPlan

A revision-planning assistant that turns a vague request ("Help me revise next week") into a
day-by-day plan, asking only for details that change the plan. It compares two ways of asking:
**Condition A** open questions, and **Condition B** suggested options with a free "Other" answer.
Module: Intelligent Interactive Systems. A2. Repository: https://github.com/shenfeixiang-123/clarifyplan

**Submitted version:** `v1.0-A2`

## Project status
| Part | Status |
|---|---|
| Slot extraction with DeepSeek (JSON mode), checked in code | Implemented |
| Ask policy in code: clarify vague answers, ask missing facts, assume or decline | Implemented |
| Condition A (open questions) and Condition B (options + Other) | Implemented |
| State panel showing what was understood, with edits | Implemented |
| Confirm step, then plan generation with DeepSeek | Implemented |
| Plan checks in code (dates, daily limit, subject coverage, days off) with one repair attempt | Implemented |
| "Why I ask" line under every question (both conditions) | Implemented |
| "Not sure / skip" for every question: visible default, or no plan without a required detail | Implemented |
| Interaction log (answer time, option vs text, skips, edits) and a per-condition summary script | Implemented |
| User study comparing A and B | Planned (Phase 3) |
| Calendar export, memory across sessions | Planned |

## Technology stack
- **Python 3.9+, Streamlit:** user interface; runs on the server, so the API key never reaches the browser.
- **DeepSeek API** via the `openai` Python SDK (OpenAI-compatible endpoint): two calls, slot
  extraction and plan generation, both in JSON mode. Model name set in `.env`.
- **pytest:** tests for the core logic with a fake client (no network).
- Undecided: whether to deploy online for the Phase 3 study.

## Running or inspecting the work
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```
- Put your DeepSeek key in `.env` (`DEEPSEEK_API_KEY`). A reviewer supplies their own key the same way;
  no key is included in this repository. Check the current model name on DeepSeek's Models & Pricing page
  and set `DEEPSEEK_MODEL`.
- **Log summary:** `python scripts/summarise_logs.py` prints a per-condition table from `logs/` (pilot use).
- **Tests:** `python -m pytest -q`. **Prompt cases:** `python scripts/run_prompt_cases.py` (needs a key).

Code map: `core/engine.py` dialogue controller · `core/policy.py` ask policy · `core/llm.py` DeepSeek calls · `core/prompts.py` prompts · `core/validator.py` checks · `core/logger.py` log ·
`docs/prompt_log.md` prompt versions and test scores.

## Development record
Significant changes only: what changed, why, and how it was checked.
Changes dated before the repository was created have no separate commit; they are all in its first commit.

| Date | Change | Why | Checked by | Commit |
|---|---|---|---|---|
| 2026-11-15 | Project skeleton: engine, ask policy, DeepSeek layer, Streamlit UI | Starting point (see AI assistance) | Read every module; `pytest` passes | — |
| 2026-11-15 | Removed record/replay mode; reviewers supply their own key | Simpler to run and explain; no recorded data needed for A2 | Tests updated; app run live | — |
| 2026-11-15 | Unanswered questions are acknowledged; vague mentions of known facts are reported, not ignored; assumed values marked *(assumed)* | Manual test: answering the constraints question with "a few hours" moved on silently | New unit tests; re-run manually | — |
| 2026-11-15 | Prompt v0.2 → v0.3: tried asking about "next Tuesday", then reverted to reading it as the coming Tuesday | v0.2 over-asked (a false alarm, Lecture 04); the date is shown before planning, so a wrong reading is cheap to fix | Prompt cases c05, c11, c12; manual test | — |
| 2026-11-15 | Constraint check by named day instead of "any weekend word" (prompt v0.5) | Manual test: "I work on Saturdays" made the code reject Sunday sessions, forced a repair and lost two study days | `blocked_days` tests (7 phrasings); manual re-test kept Sundays | — |
| 2026-11-15 | Staged progress while planning; visible subject buttons in Condition B; cleaner plan view | Planning took 15–35 s with only a spinner (> 10 s, Lecture 04); subjects were hidden in a dropdown, weakening recognition (Lecture 05) | Manual re-test of both conditions | — |
| 2026-11-16 | "Why I ask" line under each question | Says why a detail changes the plan (Amershi et al. G11); supports A1's point that questions should be focused (Rahmani et al.) | Unit test; manual run of A and B | — |
| 2026-11-16 | "Not sure / skip" on every question | Gives students a low-effort way out and makes the autonomy boundary explicit: optional details get a shown default, required ones block the plan | Unit tests for optional and required skips; manual run | — |
| 2026-11-16 | `scripts/summarise_logs.py` | Turns the interaction log into a per-condition table for a small pilot and for the Phase 3 study | Unit test on generated logs; run on local logs | — |
| 2026-11-17 | Prompt v0.6: a correction that adds a subject ("also") keeps the existing subjects | Manual test: "Actually I also need to revise chemistry" replaced Physics instead of adding Chemistry (screenshot in `docs/figures/dev_evidence/`) | Prompt cases c15, c16; manual re-test | — |
| 2026-11-23 | Prompt v0.7: constraints keep the student's meaning | Live test: "I can't study on weekday mornings" was rewritten as "only weekday afternoons and evenings", which the code read as weekends off | Prompt case c17; manual re-test of Condition A | — |
| 2026-11-23 | The plan model gets the list of available dates from the code | Live test: for an exam 16 days away the first plan used dates past the 14-day window and needed a repair (about 8 s more); counting dates is the code's job (Lecture 08) | Unit test on the prompt; manual re-test passed the checks on the first attempt | — |
| 2026-11-23 | A day off for part of the day no longer blocks the whole day | Code review: "no study on weekday mornings" would have blocked Monday–Friday | `blocked_days` tests | — |
| 2026-11-23 | Daily time rounded to quarter hours | "15 minutes a day" was rounded to 0 h | Unit test; prompt case c18; manual run gave a 15-minute plan | — |
| 2026-11-23 | No plan request when every day before the exam is a day off; the student is told why | Code review: the plan could only fail the checks in that case | Unit test | — |
| 2026-11-23 | "Subject that needs most work" kept consistent with the subject list | A priority typed via "Other" that was not a subject was never checked; a removed subject stayed marked as hardest; a live test also showed a "kept from earlier" note contradicting the new subject | Unit tests; manual run of Condition B | — |
| 2026-11-23 | Confirm step says when the plan covers only the next 14 days | Live test: exam 16 days away, but nothing said the last two days were not planned | Unit test; manual run of Condition B | — |
| 2026-11-23 | The log records why a model reply could not be read (cut off or not JSON) | Live test: two plan requests failed with "not valid JSON" and the cause could not be told from the log | Unit test | — |

## AI assistance
- **Claude (Anthropic):** generated the initial project skeleton (all modules, tests, docs templates)
  from my design: problem from my A1 review, two conditions, slots.
  I checked:   I set the scope and the constraints before any code existed, and decided which of Claude's suggestions to keep. I then went through the result module by module, ran the app on my machine and changed what did not match my brief or the lecture criteria.
- **Claude (Anthropic), testing round on 23 Nov (v0.7):** reviewed the code, ran both conditions
  with the live model, and drafted the fixes, tests and prompt changes listed for 2026-11-23.
  I checked: restarted the app and re-tested the weekday-mornings case myself
  (constraint kept as "no study on weekday mornings", weekdays planned, Geography given the most time);
  ran pytest (36 passed) and the prompt cases (25/25) on my own machine.
- **Claude (Anthropic), report drafting:** Built the framework of the report and assisted in generating the figures.
  I checked: decided the outline and what each section has to argue before drafting, and wrote
  and revised the text so that every claim traces back to the A1 review, the lecture criteria,
  the code or the logs. Checked every figure at full size against the current app, re-ran the
  diagram and storyboard scripts after the last code change, and corrected labels and screenshots
  that no longer matched.

## Additional files
- `docs/figures/`: system diagram, three storyboards and the screenshots they use.
- `docs/figures/dev_evidence/`: screenshots of problems found during development.
- `logs/`: created locally when the app runs (one JSONL file per session); not committed.
  The sidebar's *Download this session's log* button exports the current one.
