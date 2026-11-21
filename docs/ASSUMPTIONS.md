# Assumptions and things not yet verified

A-001 No second provider is needed. Both agent configurations use the Gemini API (Gemma 4 31B and
Gemini 3.1 Flash Lite). Cross-vendor comparison is therefore out of scope; results are phrased as
"these agent configurations".
A-002 Develop in GitHub Codespaces (D-005). On Windows, WSL2 is unnecessary.
A-003 Temperature 0.0 is set; some models ignore or reject it. Check when pinning model ids.
A-004 max_tokens (200000) is a placeholder; calibrate from the dry run.
A-005 CI (ci.yml) and the devcontainer were written from memory and never run. Fix on first use.
A-006 Free-tier limits (rpm/tpm/rpd) in config/agents.yaml were read from the AI Studio rate-limit page on
20 Nov 2026 and can change. Model ids are still placeholders: run `uv run tbv models` in the Codespace,
copy the exact ids, and check each model's shutdown date.
A-007 Not verified in the authoring environment (no Docker, no network, no API key):
  - DockerExecutor and the sandbox image (tests/test_sandbox_docker.py must pass on your machine)
  - GeminiProvider (written against google-genai 3.5.0 field names; first run: one easy task)
  - Gemma 4 function calling through the API (reported by third parties, not tested)
  - infra/Dockerfile.sandbox (base image digest still to be pinned)
A-008 Verified here with scripted fake agents on a test-only executor: task validation, pristine scoring,
all six verifiers, claim extraction, verdict logic, reports, retry, resumable experiment runner,
TEST-split guard, metrics and the HTML report (96 tests).
A-009 16 validated tasks exist (suite/specs). The target is 30 to 40; difficulty is uncalibrated and no
human has reviewed any task yet.
A-012 Throughput on Gemma 4 31B is limited by 16K input tokens/minute. If a step averages 4-5K tokens, that is
about 3-4 steps a minute, so roughly 1,350 steps (60 tasks with retries) take on the order of 6 hours.
This is an estimate; `tbv experiment --dry-run` replaces it with a measured projection.
A-010 Per-step token usage (about 12K in, 600 out) and request counts per run are estimates until the dry run.
A-011 Gate heuristics (hardcoding, skip markers) were tuned against scripted scenarios only. Their
precision on real agent output is unknown until labelled (Prompt 12) and must not be quoted before then.
