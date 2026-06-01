# Contributing to musubi

Thanks for considering a contribution. musubi is small, opinionated, and runs on its own dogfood — the protocol in `docs/agents/AGENT_COLLAB_RUNBOOK.md` applies to PRs against this repo too.

## Before you start

- Read `docs/agents/AGENT_COLLAB_RUNBOOK.md` and `docs/agents/PAIR_OPERATING_MODEL.md`. They define how musubi expects work to flow; PRs that ignore that shape are harder to review.
- Open an issue first for anything bigger than a typo or small bug fix. musubi is opinionated by design; the most useful early conversation is "is this the right change at all" — easier in an issue than a PR.

## What's in scope

- Orchestrator bug fixes and reliability hardening.
- Cross-platform launcher improvements (e.g. better Linux/WSL ergonomics).
- Bootstrap idempotency and merge-strategy refinements.
- Documentation clarity, especially the README onboarding path.
- Tests for the parsing functions (`over_pattern`, `extract_last_message`, `detect_sender`, `detect_writer_from_buffer`).

## What's likely out of scope

- Changes to the runbook protocol itself, the comms format, or the execution-state vocabulary. The protocol encodes specific lessons from real incidents; changes to it go through an Inspect & Adapt cycle and need evidence, not preference.
- New collaboration patterns (model routing, debate-style consensus, swarm). musubi is deliberately the asymmetric-peer pattern; other patterns belong in other repos.
- Heavyweight dependencies. The whole tool fits in one Python file plus libtmux for a reason.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

The suite (400+ tests) runs on Python 3.11–3.13 and is what CI checks on every PR. Add tests alongside any orchestrator or parsing change.

## Pull request shape

A reviewable PR has:

- **A clear single intent.** One change, one PR. Refactors and behaviour changes go in separate PRs.
- **Evidence the change works.** For orchestrator changes: a short reproduction or test output. For docs: a concrete scenario the wording was unclear in.
- **No `while I'm here` cleanups bundled into the diff.** Even if the cleanup is correct, it makes review harder.
- **A descriptive title.** Imperative, ~50 chars: "Fix X" not "Updated some stuff".

If your change touches `bootstrap.sh`, any file under `docs/agents/`, or any file under `templates/`, the change propagates to every project that runs bootstrap. Be conservative — these are managed artefacts.

## Review

Reviews follow the runbook's review pattern: reviewers read actual files (not just the diff summary), check the change against its stated intent, and surface concrete findings. "Looks fine" is not a review result.

## License

By contributing, you agree your contribution will be licensed under the MIT License (see `LICENSE`).
