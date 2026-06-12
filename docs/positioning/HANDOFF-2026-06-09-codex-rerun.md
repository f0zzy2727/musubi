# Handoff — musubi positioning analysis rerun

Date: 2026-06-09
Repo: `~/Dev/musubi.repo`

## Where We Are

User asked Codex to inspect Claude's analysis method at
`docs/positioning/ANALYSIS-METHOD.md`, rerun what could be rerun, and assess the
overall result against Claude's existing positioning docs.

Relevant repo artifacts:

- `docs/positioning/ANALYSIS-METHOD.md` — untracked file from Claude describing
  the reproducible method.
- `docs/positioning/benchmark-results-2026-06.md` — Claude's existing benchmark
  result.
- `docs/positioning/benchmark-results-2026-06-09-codex-rerun.md` — new Codex
  rerun artifact created this session.
- `scripts/comms-metrics.py` — deterministic Track 1 metrics script.

Current git status at save time:

```text
?? docs/positioning/ANALYSIS-METHOD.md
?? docs/positioning/HANDOFF-2026-06-09-codex-rerun.md
?? docs/positioning/benchmark-results-2026-06-09-codex-rerun.md
```

No existing tracked files were edited.

## What Was Run

Phase A corpus spine check over:

- `~/Dev/aic/cc-aic/docs/agents`
- `~/Dev/1-in-a-billion-paradise/docs/agents`
- `~/Dev/portfolio-experiment/docs/agents`

Observed:

```text
cc-aic lines=157524 Type=4710 OVER=5120 @OYA=1945
1-in-a-billion lines=79886 Type=1942 OVER=1981 @OYA=586
portfolio lines=11551 Type=336 OVER=338 @OYA=798
```

Track 1 command:

```sh
python3 scripts/comms-metrics.py \
  ~/Dev/aic/cc-aic/docs/agents \
  ~/Dev/1-in-a-billion-paradise/docs/agents \
  ~/Dev/portfolio-experiment/docs/agents \
  --json /tmp/comms-metrics.json
```

Track 1 reproduced Claude's numbers exactly. Key values:

- cc-aic: SEI `0.0529`, duplicate rate `0.296`, zero-finding approve `0.674`.
- 1iab: SEI `0.0721`, duplicate rate `0.050`, zero-finding approve `0.780`.
- portfolio: SEI `0.1420`, duplicate rate `0.095`, zero-finding approve `0.278`.

Track 2 fresh independent rater:

- Spawned one fresh sub-agent, no prior context, with the rubric from
  `ANALYSIS-METHOD.md`.
- Files sampled:
  - cc-aic `comms/active.txt` and
    `archive/agent_comms_2026-06-09_hardening-sprint.txt`
  - 1iab `comms/active.txt` and
    `archive/comms-active-archive-20260606-113538.md`
  - portfolio `comms/active.txt` and
    `archive/agent_comms_2026-06-09_125311.txt`

Fresh rater headline:

- NOTECHS mean: cc-aic `7.75`, 1iab `8.25`, portfolio `6.50`, overall `7.48`.
- MARBLE-style score: cc-aic `8`, 1iab `8`, portfolio `5`.
- Convergence: cc-aic `7` disagreements, `71%` <=1 exchange; 1iab `7`
  disagreements, `71%` <=1 exchange; portfolio `0 found in supplied files`;
  overall `14` disagreements, median `1`, `71%` <=1 exchange, `4` multi-round,
  `7` procedural/rubber-stamp approvals.

## Current Assessment

Codex assessment given to user:

Claude's deterministic story is solid and reproducible. The framework has strong
turn discipline, real evidence scaffolding, Oya catches real issues, peer review
catches real issues, and the protocol is meaningfully portable across software
and non-software test beds.

The sharper caveat is convergence/debate. Claude's existing Track 2 presented
convergence as a moderate weakness: 44% single-exchange, 56% multi-round, zero
rubber-stamps. Codex's fresh rater was stricter on newer sampled files: 71%
single-exchange in cc-aic/1iab, portfolio not deeply rateable from latest files,
and no sustained counter-position after hard evidence.

Best combined positioning:

> Musubi is defensibly "evidence-governed multi-agent judgment with human
> sovereignty." It is not yet strongly proven as "robust adversarial
> deliberation." The protocol works; the debate claim needs tighter measurement.

## Suggested Next Steps

1. Decide whether to keep `benchmark-results-2026-06-09-codex-rerun.md` as a
   standalone appendix or fold a short caveat into `benchmark-results-2026-06.md`.
2. If updating the main benchmark doc, avoid overwriting Claude's rater result;
   present the Codex rerun as a second-rater / newer-sample sensitivity check.
3. Add a `Slice:` grouping key to the comms protocol before treating exact
   premature-consensus percentages as publishable.
4. Consider running a second independent rater on the same sample to measure
   whether the Track 2 disagreement is sample variance or rater variance.

## Suggested Skills

- `source-command-gsd-ns-review` if the next task is to audit the positioning
  claims for defensibility.
- `source-command-gsd-ns-workflow` if the next task is to plan edits across the
  positioning docs.
- `github:yeet` only if the user asks to commit/push/open a PR.

