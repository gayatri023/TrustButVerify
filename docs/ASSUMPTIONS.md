# Assumptions and things not yet verified

A-001 No second provider is needed. Both agent configurations use the Gemini API (Gemma 4 31B and
Gemini 3.1 Flash Lite). Cross-vendor comparison is therefore out of scope; results are phrased as
"these agent configurations".
A-002 Develop in GitHub Codespaces (D-005). On Windows, WSL2 is unnecessary.
A-003 Temperature 0.0 is set; some models ignore or reject it. Check when pinning model ids.
A-004 max_tokens (200000) is a placeholder; calibrate from the dry run.
A-005 CI (ci.yml) and the devcontainer were written from memory and never run. Fix on first use.
A-006 Model ids and free-tier limits (rpm/rpd) are NOT filled in: copy them from AI Studio, and check each
model's shutdown date. Third-party sources reported Gemma 4 31B at 15 rpm / 1500 rpd and Gemini 3.1
Flash Lite at 500 rpd; these are unverified.
A-007 Not verified in the authoring environment (no Docker, no network, no API key):
  - DockerExecutor and the sandbox image (tests/test_sandbox_docker.py must pass on your machine)
  - GeminiProvider (written against google-genai 3.5.0 field names; first run: one easy task)
  - Gemma 4 function calling through the API (reported by third parties, not tested)
  - infra/Dockerfile.sandbox (base image digest still to be pinned)
A-008 Verified here with scripted fake agents on a test-only executor: task validation, pristine scoring,
all six verifiers, claim extraction, verdict logic, reports, retry, resumable experiment runner,
TEST-split guard, metrics and the HTML report (96 tests).
A-009 The 5 included tasks are examples. The 60-task suite is not written yet; difficulty is uncalibrated.
A-010 Per-step token usage (about 12K in, 600 out) and request counts per run are estimates until the dry run.
A-011 Gate heuristics (hardcoding, skip markers) were tuned against scripted scenarios only. Their
precision on real agent output is unknown until labelled (Prompt 12) and must not be quoted before then.
