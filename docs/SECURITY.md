# Security

Threat model: agents produce arbitrary code and shell commands. All of it runs only inside the
sandbox (Prompt 4). Hidden tests are mounted only into a fresh scoring container after the
agent container is destroyed.

Sandbox tests (tests/test_sandbox_docker.py). WRITTEN, NOT YET RUN: they need Docker and the image
(`make docker-tests` in the Codespace). Until they pass, treat the sandbox as unproven.
- agent container cannot reach the network
- runs as a non-root user
- cannot write outside the workspace (read-only root filesystem)
- hidden tests are not visible inside the agent container
- infinite loop times out; fork bomb is contained by the PID limit
- huge output is truncated
- no Docker socket inside the container; no containers left behind

Container settings (unit-tested): network none, all capabilities dropped, no-new-privileges, user
1000, memory/CPU/PID limits, read-only root with a tmpfs /tmp, hidden tests mounted read-only and only
into the scoring container.

Known limitations (honest list):
- Scoring runs agent code in the same process as the tests. An agent that deliberately attacks the
  scorer (for example an atexit hook that rewrites the report) is out of scope; the junit file name is
  unguessable and cross-checked with the exit code, which stops accidents, not a determined attacker.
- LocalExecutor has NO isolation. It exists for trusted fixtures only (D-006).
- Free-tier Gemini requests may be used by Google to improve products; do not send anything private.
- Docker-in-Docker inside Codespaces adds a second isolation layer but is also unverified.

Leakage rule: hidden tests, hidden requirements and reference patches must never appear in
agent prompts, transcripts, the retry message, gate inputs or logs (audited in Prompt 15).

Secrets: API keys live in .env (gitignored) and are never passed into agent containers.
