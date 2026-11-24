# Prompt log

One row per prompt change. Change one thing at a time, then rerun
`python scripts/run_prompt_cases.py` and record the score (Lecture 09).

Scores for v0.1–v0.4 were not recorded, and those prompts were changed before the repository
existed, so they cannot be re-run. v0.5 and v0.6 were re-run on 24 Nov from their own versions of
the code: first on the cases that existed at the time, then on the v0.7 case set (in brackets).
The model is not deterministic, so a re-run can differ from a run on the day.

| Version | Date | Change (one thing) | Why | Score | Commit |
|---|---|---|---|---|---|
| v0.1 | 2026-11-15 | First version of extraction and plan prompts | Baseline | not recorded | |
| v0.2 | 2026-11-15 | Extraction: "next &lt;weekday&gt;" is marked ambiguous with both candidate dates in the note (JSON example changed to an explicit date so it does not contradict the rule) | Manual test: "next Tuesday" said on Sun 15 Nov was read as Tue 17 Nov without asking; the exam date changes the whole plan, so this is worth a question. Case c05 now expects "ambiguous"; c11 added for an explicit date | not recorded | |
| v0.3 | 2026-11-15 | Extraction: replaced the v0.2 rule. Weekday names resolve to the first such weekday after TODAY ("Tuesday after next" = the second) and count as stated | Manual test of v0.2: asking about "next Tuesday" felt unnecessary, since most people mean the coming Tuesday. Over-asking is a false alarm (Lecture 04) and adds effort A1 aims to reduce. The resolved date is already shown in the confirm step and state panel, so a wrong reading is cheap to correct. c05 back to an exact date; c12 added | not recorded | |
| v0.4 | 2026-11-15 | Extraction: the `note` for an ambiguous value must be a few plain words addressed to the student | Manual test: the clarify turn showed the model's internal note ("Student is unsure; 'maybe' does not confirm…"), which is written for code, not for the student | not recorded |  |
| v0.5 | 2026-11-15 | Extraction: constraints written as "no study on <days>" / "only <days or times>"; one message may fill several fields; notes at most 8 words and must not repeat the student. Plan: list only days with sessions; never mention corrections | Manual test of both conditions: "on Saturdays" was read by code as the whole weekend; "2.5 hours on weekdays" lost the weekday constraint; a clarify note repeated the quote; after a repair the plan said "following the correction". Cases c13 and c14 added | 19/19 (23/25 on v0.7 cases) |  |
| v0.6 | 2026-11-17 | Extraction: subjects is the complete list after the message; "also/too" adds to the current list, "instead/only" replaces it | Manual test while capturing storyboards: "Actually I also need to revise chemistry" replaced Physics with Chemistry, because the prompt told the model to report only facts from the latest message. Cases c15 and c16 added | 21/21 (24/25 on v0.7 cases) |  |
| v0.7 | 2026-11-23 | Extraction: constraints keep the student's meaning ("no study on <days and times>"; "only" only if the student says only/just). Plan: the code passes the list of AVAILABLE DATES (window and whole days off removed); a part-day constraint does not remove the day; assumptions must not repeat the facts | Live test of both conditions: "I can't study on weekday mornings" became "only weekday afternoons and evenings", which the code then read as weekends off; a 16-day plan used dates past the 14-day window and needed a repair; after the first fix the plan left all weekdays empty; assumptions restated stated facts. Cases c17–c19 added | 25/25 | |
