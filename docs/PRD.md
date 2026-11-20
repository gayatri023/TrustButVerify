# PRD 3: TrustButVerify (condensed)

Condensed from PRD 3 v1.0. Every number is a target, parameter or placeholder, not a result.

One line: a tool that checks a coding agent's claim of "done" against evidence (test runs,
builds, diffs, the agent's command trace), returns a verdict, and ships with a task suite that
measures how often agents claim completion falsely.

Product question: what evidence should a developer see before trusting "done", and what does
it cost in time and tokens?

Failure shapes: unsupported claim (never ran tests after last edit), contradicted claim (ran
them, they failed), incomplete but passing (visible pass, hidden fail).

Non-goals: a new agent, SWE-bench scale, formal verification, style grading, security
scanning, claims about agents in general.

Requirements
  P0: TB-1 task format and validator; TB-2 agent runner and transcripts; TB-3 Docker sandbox;
      TB-4 claim extractor; TB-5 verifiers; TB-6 verdict report (CLI, JSON, PR comment);
      TB-7 one-retry loop; TB-8 experiment runner; TB-9 analysis report.
  P1: TB-10 GitHub Action; TB-11 100 human-labeled claims; TB-12 developer study;
      TB-13 JavaScript tasks.
  P2: TB-14 failure dashboard.

Suite: 80 to 100 Python tasks; automatic validation; 15 hand-reviewed; pilot of 10 tasks
calibrated toward 40 to 80 percent success; 20 TEST tasks never used for tuning.

Metrics and hypotheses: see docs/PREREG.md.
