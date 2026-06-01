## What changed

<!-- One concrete sentence describing the diff. Not "improved the orchestrator" but "added a config-validation pre-flight step in load_config". -->

## Why

<!-- The trigger or motivation. Link an issue or a runbook section if relevant. -->

## Validation

<!-- How you tested. For orchestrator changes: pytest output or a repro. For docs: the scenario the previous wording was unclear in. -->

- [ ] `pytest tests/` passes
- [ ] `bash -n bootstrap.sh launch_musubi*.sh scripts/*.sh` passes
- [ ] No "while I'm here" cleanups bundled in
- [ ] If touching `bootstrap.sh`, `docs/agents/`, or `templates/`: change is conservative and propagation-aware

## Notes for the reviewer

<!-- Anything reviewers should know that isn't obvious from the diff. Rejected alternatives. Edge cases considered. -->
