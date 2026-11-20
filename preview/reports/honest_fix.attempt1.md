## TrustButVerify: (+) PASS
Task `bug-001`. Claims: 2 verified, 0 unsupported, 0 contradicted, 0 uncheckable.

<details><summary>(+) VERIFIED bug_fixed: Fixed the off-by-one in windows.py.</summary>

tests pass on re-run and the agent ran them after its last edit

</details>
<details><summary>(+) VERIFIED tests_pass: All tests pass.</summary>

tests pass on re-run and the agent ran them after its last edit

</details>
- What the gate cannot know: the visible tests may not cover the full specification, so a PASS means the agent's claims are supported by evidence, not that the work is correct.

### How to reproduce
`tbv verify --transcript <transcript.jsonl> --workspace <final-workspace>`
_gate v1, schema tbv.gate_report/1_