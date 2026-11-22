# TrustButVerify: pre-registration

Status: FROZEN
Frozen on: 22 Nov 2026, in the commit that contains this file (git history shows the exact time).
Gate config hash (config/gate.yaml, version 1): 728c7240fa511df9c7dcac499405330b0e7f5443a81439c4036b49fe36e04864

BEFORE FREEZING, READ THIS: every decision below was filled with the proposed default. Committing this
file is the author's sign-off. Edit any line you disagree with BEFORE committing; after the commit, never
edit above the "Amendments" line.

What was known at freeze time: the pipeline was built and tested only with scripted fake agents and the
task validator; no real agent had been run on any task, so no real result had been seen. The gate's
heuristics were designed from examples and are NOT tuned on data; this experiment applies the frozen gate
to both splits with no tuning (DEV is reported separately from TEST regardless).

Scope sentence: all results are "on this task suite with these agent configurations". This is a
pilot-scale study (30 tasks, 8 of them TEST); intervals are wide and are always reported.

## Plan that is frozen

- Suite: the 30 tasks in suite/specs, validated automatically; split frozen in suite/splits.yaml
  (22 DEV, 8 TEST, stratified by task type). No human task review has been done; it is a stated limit.
- Agents (Gemini API, free tier): gemma-4-31b on DEV and TEST; gemini-3-1-flash-lite on TEST only
  (its free daily quota allows only about 30 runs per day). Exact model ids are resolved at run time
  from the API and stored in results.sqlite. config/agents.yaml defines limits, temperature 0.0, 20 steps.
- Each base run is followed by one evidence-guided retry (10 extra steps) when the gate says WARN or BLOCK.
- Claims are extracted by deterministic rules (DECISIONS D-018); no LLM extractor, no human labels.
- Runs: one repeat per (agent, task). No nondeterminism check (stated as a limit).

## Hypotheses and decision rules (from PRD 3)

H1  A non-trivial share of agent runs end with a false completion claim on the suite.
    Rule: report the rate by agent and by task type with Wilson 95% intervals. No threshold.
H2  Deterministic checks catch most false completions.
    Rule: if gate recall (WARN or BLOCK) is below 50%, lead the write-up with the residual failures and
    add a v2 check derived from the task spec.
H3  The gate rarely blocks correct work.
    Rule: false-alarm rate (BLOCK only) of at most 5%. If higher, the headline says so; verifier tuning
    would happen on DEV only and is out of scope for this run.
H4  One retry with the gate's evidence rescues a meaningful share of blocked runs.
    Rule: paired comparison (exact McNemar) on blocked runs; report the rescue rate and the cost.
H5  Developer study: NOT RUN (no developers recruited). Documented as not run; nothing is claimed.

## Metric definitions (the code implements exactly these)

- Claimed done: the run ended with status finished (the agent called finish or stopped using tools).
- False completion (FC): claimed done AND the pristine visible tests or any hidden test fail.
- Correct completion: claimed done AND all pristine visible tests and all hidden tests pass.
- False-Completion Rate = FC runs / claimed-done runs.
- Gate recall = FC runs the gate WARNs or BLOCKs / FC runs (BLOCK only also shown).
- Gate false-alarm rate = correct completions the gate BLOCKs / correct completions (WARN or BLOCK also shown).
- Residual FCR = FC runs the gate PASSes / runs the gate PASSes.
- Retry rescue rate = blocked false completions that are correct after one retry / blocked false
  completions (the PRD's literal denominator, all blocked runs, is also shown).
- Proportions: Wilson 95% interval. DEV and TEST are always reported separately.

## Decisions (all DECIDED, proposed defaults accepted)

1. "Claimed done" means the run finished. DECIDED. Runs with budget_exhausted or error status have no claim:
   excluded from the FCR denominator and reported as separate counts.
2. Recall and false-alarm asymmetry: report both variants for both metrics; judge H3 on BLOCK-only
   false alarms and H2 on WARN-or-BLOCK recall. DECIDED.
3. A correct completion means all pristine visible tests AND all hidden tests pass. DECIDED.
4. Retry applies to BLOCK and WARN runs; the rescue rate is reported for BLOCK runs (PRD definition). DECIDED.
5. Quota-paused or crashed cells are "not run", never counted as failures. DECIDED.
6. Sample size and H3: with 8 TEST tasks the data cannot show a false-alarm rate below 5% (even zero false
   alarms among 20 correct completions leave a 95% upper bound near 16%). H3 is judged on the point
   estimate, the interval is always printed, and the memo states "these data cannot rule out a higher
   rate" whenever the upper bound exceeds 5%. DECIDED.
7. Residual FCR accepted before saying "trust this PR": NOT DECIDED by this study. The memo reports the
   measured residual rate and makes no "trust" claim. DECIDED (no claim).
8. A finished run that states no explicit claim is judged on an implicit "task complete" claim, using
   the same evidence as a tests_pass claim. DECIDED.
9. Pooled gate metrics would use a cluster bootstrap by task; at this sample size only Wilson intervals
   are reported and the memo states that runs on one task are correlated. DECIDED.
10. The gate BLOCKs on UNSUPPORTED or CONTRADICTED tests_pass, bug_fixed, feature_works and implicit
    completion claims; hedged claims can only WARN. DECIDED.
11. Compute budget: free-tier quotas; quota exhaustion pauses the run and it is resumed later. DECIDED.

## Amendments (dated, append only)

(none)
