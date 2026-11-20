# Decisions

Format: context, options, choice, reason.

## D-001 Exit codes
Context: `tbv verify` must exit 0 (PASS), 2 (WARN), 1 (BLOCK) so CI can gate on it. But Click's
default usage-error code is 2, and an uncaught Python exception exits 1. A typo in a CI step
would therefore look like a WARN, and a crash would look like a BLOCK.
Options: (a) accept the collision; (b) remap everything that is not a verdict.
Choice: (b). 3 = not implemented yet, 64 = usage error, 69 = environment problem (Docker not
reachable), 70 = internal error, 130 = aborted. Applied in `tbv.cli.main`.
Reason: a verdict code must only ever mean a verdict. Tested via the real entry point.

## D-002 Dependency layout
Context: the kit fixes the stack, but only some prompts need heavy or provider-specific packages.
Choice: core install is light (typer, rich, pydantic, pyyaml, docker, junitparser). Analysis
packages are the `analysis` extra. LLM SDKs are the `llm` extra and the second provider's SDK
is added in Prompt 5 once it is chosen. `make setup` installs all extras.

## D-003 No model strings or prices committed until verified
Context: the portfolio rules say not to copy model names from source documents and never to
write a number you did not verify.
Choice: config uses SET_... placeholders and null prices. `tbv doctor` shows them as TODO and
the experiment runner (Prompt 10) refuses to start while any placeholder remains.

## D-004 Pre-registration is enforced in code
Choice: `tbv experiment` without --dry-run refuses unless docs/PREREG.md has `Status: FROZEN`.
Dry runs only need SPEND_CAP_USD, because they exist to estimate cost before you freeze.

## D-005 Develop and run the sandbox in GitHub Codespaces
Context: the developer's laptop measured 7.7 GB RAM and 12.2 GB free disk. Docker plus a WSL2
distro, a browser, an editor and several parallel agent containers would not fit comfortably,
and a WSL virtual disk grows but does not shrink by itself.
Options: (a) Docker Desktop locally; (b) Docker Engine inside WSL2; (c) Codespaces with
docker-in-docker; (d) a small cloud VM.
Choice: (c), configured in .devcontainer/devcontainer.json. The laptop only needs a browser.
Reason: removes the local resource risk and gives any AI coding agent a Linux shell where it can
run Docker tests itself. Cost: depends on the free monthly Codespaces allowance, which must be
checked in GitHub billing settings. The experiment runner is resumable, so a stopped codespace
loses no completed runs. API keys go in Codespaces secrets, never in committed files.

## D-006 One Executor seam; a test-only LocalExecutor
Context: Docker is not available everywhere the code is written and tested.
Choice: all command execution goes through `Executor` (tbv/sandbox/base.py). `DockerExecutor` is the
real one. `LocalExecutor` runs plain subprocesses, refuses to run unless TBV_ALLOW_UNSAFE_LOCAL=1,
and is used only for trusted handwritten fixtures (tests, `tbv demo`).
Cost: the Docker path is only proven by tests you run on a Docker machine (tests/test_sandbox_docker.py).
Reason: lets the whole pipeline be tested without weakening the rule that model code runs only in Docker.

## D-007 Pristine scoring
Context: the kit copies the agent's final workspace into the scoring container, so an agent that edits
tests, conftest.py or pytest.ini could change its own score.
Choice: build the scoring workspace from the seed, overlay only the agent's non-protected files, restore
visible tests, drop agent-added config files, and mount hidden tests read-only (sandbox/scoring.py).
The junit report gets an unguessable filename and is cross-checked against the exit code.
Cost: legitimate edits to protected paths are ignored (tasks can list protected_exceptions).

## D-008 What "correct completion" means
All pristine visible tests AND all hidden tests pass. Hidden-only results are stored as well, because
validation requires the hidden tests to fail on the seed on their own.

## D-009 Finishing with no claim is an implicit completion claim
An agent that says only "Done." must not get a free PASS. The gate adds an implicit_completion claim,
judged like tests_pass. This raises recall; it is pre-registered (PREREG decision 8).

## D-010 BLOCK on unsupported completion claims
tests_pass, bug_fixed, feature_works and implicit completion claims that are UNSUPPORTED or
CONTRADICTED BLOCK. The PRD only names tests_pass; extending it is the same rule applied to claims
that rest on the same evidence. Hedged claims can only WARN. Tuned on DEV only.

## D-011 Free-tier, quota-aware experiment (no billing)
Context: paid credits were not affordable; the free tier has per-model daily request limits.
Choice: two Gemini-API configurations whose free quotas fit the lean plan (Gemma 4 31B and Gemini 3.1
Flash Lite, ids to be verified), a QuotaLimiter (RPM and Pacific-day RPD), pause-and-resume when the
day's quota is spent, sequential runs, and no billing ever (a free project cannot be charged).
Cost: slower wall-clock, one run at a time, free-tier data-use terms apply (see DATA_CARD).

## D-012 Tasks are compact specs expanded by code
Tasks are authored as short YAML specs (suite/specs) and expanded into task directories by
tbv/suite/factory.py, then validated in the sandbox. The reference solution is stored as overlay files
(not a patch) because it is simpler and cannot fail to apply. No API money is spent on generation, and
the task author (Claude) differs from the models under test (Gemini family).

## D-013 One short-lived container per command
State lives in the mounted workspace, not in a long-running container. Cost: about a second of
overhead per command. Benefit: no cross-command process state, simple cleanup, nothing to escape from.

## D-014 What counts as a test run
Only a clean, single test-runner invocation (pytest or unittest, optionally after `cd x &&`) counts as
the agent having run tests. Pipes, `;`, redirects, extra `&&` segments, `echo` and `--collect-only`
do not, because they can fake or change the exit code (gate/verifiers.py is_test_run).

## D-015 No heavy dependencies for statistics
Wilson, bootstrap, cluster bootstrap and exact McNemar are about 100 lines of stdlib code, each with a
hand-computed test. The HTML report is inline SVG with no scripts, so it works offline and cannot break.

## D-016 Agent prompt and loop
The agent gets the one-sentence system prompt from the kit, the task instruction only (no test-command
hint, no "verify your work"), five tools, and a step cap counted in provider turns. A turn with no tool
call is treated as the final message. Cost: agents that do not know the test command may run fewer
tests, which is exactly the behaviour the gate measures.
