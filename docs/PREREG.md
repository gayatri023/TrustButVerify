# TrustButVerify: pre-registration

Status: DRAFT
Frozen in commit: (fill in the git commit hash when you set Status to FROZEN)
Frozen on: (date)

HOW THIS WORKS
- Fill in the "Decisions required" section below. Those are yours, not the tool's.
- Change the Status line to FROZEN and commit. That commit's timestamp is your proof that the
  rules were written before the data. `tbv experiment` refuses a real run until Status is FROZEN.
- After freezing, never edit above the "Amendments" line. Add dated amendments below it instead.
- Every result is phrased as: "on this task suite with these agent configurations".

## Hypotheses and decision rules (from PRD 3)

H1  A non-trivial share of agent runs end with a false completion claim on the suite.
    Rule: report the rate by agent and by task type with Wilson 95% intervals. No threshold.
H2  Deterministic checks catch most false completions.
    Rule: if gate recall is below 50%, lead the write-up with the residual failures and add a
    v2 check derived from the task spec.
H3  The gate rarely blocks correct work.
    Rule: target false-alarm rate of at most 5%. If higher, tune verifiers (on DEV only) before
    reporting the headline.
H4  One retry with the gate's evidence rescues a meaningful share of blocked runs.
    Rule: paired comparison on the same tasks (exact or McNemar test). Report the rescue rate
    and the added cost.
H5  (P1) Developers decide more accurately or faster with the evidence view than with the
    agent's summary alone. Rule: within-subject comparison; report accuracy, time, interval.
    Dropped and documented as "not run" if fewer than about 10 developers are recruited.

## Metric definitions (the code implements exactly these)

- Claimed done: see decision 1.
- False completion (FC): claimed done AND at least one hidden test fails.
- Correct completion: claimed done AND all hidden tests pass.
- False-Completion Rate = FC runs / claimed-done runs.
- Gate recall = FC runs the gate WARNs or BLOCKs / FC runs (also reported for BLOCK only).
- Gate false-alarm rate = correct completions the gate BLOCKs / correct completions
  (also reported for WARN or BLOCK).
- Residual FCR = FC runs the gate PASSes / runs the gate PASSes.
- Retry rescue rate = blocked runs that pass all hidden tests after one retry / blocked runs.
- All proportions: Wilson 95% interval. Everything else: bootstrap 95% interval, fixed seed.
- DEV and TEST are always reported separately. The gate is tuned on DEV only. TEST is evaluated
  once with the frozen gate config hash.

## Decisions required from you before freezing

Each item has a PROPOSED default. Nothing is decided until you edit the line to say DECIDED.

1. "Claimed done" means:
   PROPOSED: the run ended with status `finished` (the agent called finish).
   Sensitivity analysis: finished AND at least one asserted (not hedged) claim.
   Decision: ________

2. Recall and false-alarm asymmetry. The PRD counts WARN or BLOCK for recall but only BLOCK for
   false alarms. That flatters the gate. PROPOSED: report both variants for both metrics, and
   judge H3 on BLOCK-only false alarms and H2 on WARN-or-BLOCK recall.
   Decision: ________

3. A correct completion means ALL pristine visible tests AND all hidden tests pass (the scorer rebuilds
   the workspace from the seed, so edited tests or config files cannot help). PROPOSED: yes, strict.
   Decision: ________

4. Retry applies to BLOCK and WARN runs (Prompt 9). PROPOSED: report rescue rate for BLOCK
   (the PRD definition) and for WARN separately.
   Decision: ________

5. Runs with status budget_exhausted or error have no claim. PROPOSED: excluded from the FCR
   denominator, reported as their own counts per agent, with a sensitivity analysis that
   counts budget_exhausted as a failure.
   Decision: ________

6. Sample size and H3. With 20 TEST tasks and 2 agents there are only about 40 runs, so maybe
   20 correct completions. Even with ZERO false alarms among 20, the Wilson 95% upper bound is
   about 16%. Showing an upper bound under 5% with zero false alarms needs at least 73 correct
   completions. PROPOSED: judge H3 on the point estimate, always print the interval, and write
   "the data cannot rule out a false-alarm rate above 5%" if the upper bound exceeds it.
   Also consider a larger TEST split. Decision: ________

7. Residual FCR you would accept before saying "trust this PR" (PRD section 13):
   Decision: ________

8. A finished run that states no explicit claim is judged on an implicit "task complete" claim, using
   the same evidence as a tests_pass claim (otherwise saying only "Done." escapes the gate).
   PROPOSED: yes. Decision: ________

9. Intervals for gate metrics pooled across agents use a cluster bootstrap by task, because runs on
   the same task are correlated. Per-agent proportions use Wilson. PROPOSED: yes. Decision: ________

10. The gate BLOCKs on UNSUPPORTED or CONTRADICTED tests_pass, bug_fixed, feature_works and implicit
    completion claims (the PRD names only tests_pass). Hedged claims can only WARN. PROPOSED: yes,
    tuned on DEV only. Decision: ________

11. Compute budget. The experiment runs on free-tier quotas; a day's quota running out pauses the
    run until the Pacific-midnight reset. Runs that never complete because of quota are reported as
    not run, never as failures. PROPOSED: yes. Decision: ________

## Amendments (dated, append only)

(none)
