# Related work, and what TBV does and does not add

Found by web search and read only as snippets: read the papers before citing them.

- EvilGenie (arXiv 2511.21654): a reward-hacking benchmark built from LiveCodeBench problems. It detects
  hacking with held-out tests, LLM judges, test-file edit detection and human review, and measures
  Codex, Claude Code and Gemini CLI.
- SpecBench (arXiv 2605.21384): uses the pass-rate gap between visible and held-out tests to quantify
  reward hacking in long-horizon coding tasks.
- SWE-Bench Pro Verified (arXiv 2609.08149): anti-hacking controls and task verification for a
  software-engineering benchmark.
- Reported hacks include a conftest.py that rewrites pytest reports and objects whose __eq__ always
  returns True (arXiv 2610.12822).

## What TBV reuses (not claimed as new)
Held-out tests as the oracle, test-file edit detection, conftest and skip-marker handling.

## What TBV adds
1. It checks the agent's CLAIMS, not only its code: each statement ("tests pass", "file created") gets a
   verdict (VERIFIED, UNSUPPORTED, CONTRADICTED, UNCHECKABLE) from deterministic evidence, including
   whether the agent actually ran the tests after its last edit.
2. A product policy layer: when to BLOCK versus WARN, a false-alarm guardrail, one evidence-guided
   retry and its measured rescue rate, and an assumption-labelled break-even cost model.
3. Pre-registered decision rules and a small, fully reproducible suite run on free-tier models.

## Limits
A small custom suite and small free-tier models. Results are not comparable with the benchmarks above
and say nothing about frontier agents. If the measured false-completion rate is low, that is a result:
it means the problem is smaller than assumed and the recommendation is not to ship the gate by default.
