# Developing Sword Forge (rules for any AI or person)

Sword Forge is meant to get better with every weapon it produces. Any assistant that uses it may also improve it, but only this way.

## 0. Evidence first: a live test beats any general knowledge

A change counts only when a run here proves it. "Experts recommend X", "it is best practice", "I read that…" is not a
reason to change Sword Forge. It is an **idea** until it has been tried on a real or test sword and measured.

- **Ideas** (untested): `record_lesson("idea", title, what)`. They are stored and flagged `tested: false`. They never
  change the code or the thresholds.
- **Changes** (code, `config.json`, `weapon_profiles.json`): try them on `forge_selftest` (or another project listed in
  `config.test_projects`), measure before and after with the same checks, then
  ```python
  record_experiment(title="Euclidean UV padding", change="disk dilation in uv_pack", hypothesis="true 16 px gaps",
                    files=["forge_uv.py"], runs=[{"project": "forge_selftest", "step": "s3_forge", "report": r"D:\...\reports\s3_uv\report.json"}],
                    before={"min_gap_px": 10.47}, after={"min_gap_px": 17.2},
                    evidence=[r"D:\...\reports\s3_uv\uv_audit.json", r"D:\...\diagnostics\uv_islands.png"], result="better")
  ```
  It is refused without measured before/after values, an existing run report and existing evidence files.
  `result` "better", "same" or "mixed" registers the md5 of the changed files in `manifest.json`; "worse"/"failed" are
  kept as evidence and register nothing.
- **Enforced**: at load time every file is compared with `manifest.json`. A file changed without an accepted
  experiment is *untested*: `forge_cli` runs it only on test projects and refuses real projects (exit code 4).
- An `error` or `success` lesson needs existing evidence files too.
- Sources for reference data (`weapon_profiles.json`) are written next to each range. A range without a source is a
  guess: it can raise REVIEW, never FAIL, until a source or a measurement replaces it.

## 1. Record what happens while producing (always)

- **Every stage result is logged automatically**:
  - all projects: `<studio>\forge_ledger.jsonl` (stage results, approvals, orchestrator errors and retries; one JSON per line)
  - per project: `orch_journal.json` and `logs/`
- **Lessons**: when something goes wrong, or works noticeably well, record it at once:
  ```python
  record_lesson("error", "gem showed seam lines", what="7 UV seams met at the gem centre",
                cause="normal-cone charts cut the sphere", fix="gem as one chart", gate="s3 seam_placement REVIEW",
                project="inferno_dragon_sword", stage="s3_uv", evidence=[r"D:\...\reports\s4_bake\comparison\sheet.png"])
  record_lesson("success", "headless stages", what="s0 took 7 s headless vs 3.5 min in the UI", project="forge_selftest")
  ```
  `kind` is one of `error`, `success` or `idea`. This appends to `forge/lessons.jsonl` and regenerates `LESSONS_LOG.md`.
- Set your name before running: environment variable `FORGE_AGENT=claude|chatgpt|gemini|codex|<person>`. The ledger and the lessons record who did what.

## 2. Change the code (only like this)

1. **Never edit the production folder while a queue is running.**
2. Copy `forge/` to `forge_dev/`, change it there, and change only what the lesson or task needs. Reuse the existing tools. Do not rewrite them.
3. Keep the public functions and their arguments unchanged. If you must change one, keep the old name working.
4. Run the self-test queue against `forge_dev`:
   `python forge_orch.py run <studio>\forge_selftest_queue.json`
   It must reach the same or better results, and the injected failure must still be retried and resumed.
5. Copy the files back. **Verify every copied file by MD5 inside Blender**: file transfers have delivered stale copies before.
6. Bump `FORGE_VERSION` in `forge.py` only if finished steps must be redone. That changes the fingerprints.
7. Call `record_experiment(...)` with the measured before/after (rule 0), then write a `CHANGELOG.md` entry: date,
   agent, what changed, why (link the lesson), and the experiment id.
8. Update `ROADMAP.md` (what is built, tested, or still missing) and, if it is a lasting rule, `LESSONS.md` (mistake → gate).

## 3. Never

- Lower a threshold to make a sword pass. Record a lesson and discuss calibration instead.
- Change code or reference data because of general knowledge alone. Try it, measure it, record the experiment.
- Hide a critical failure behind a good total score.
- Delete reports, logs, the ledger or lessons. They are the evidence.
- Use PowerShell, download files, use paid services, change MCP config, or publish or submit anything without the user's explicit OK.
