# CLAUDE.md — operating conventions for this repo

Conventions for any Claude Code session working **on musubi itself**. The
agent-pair operating discipline lives elsewhere and is not repeated here:

- Per-cycle pair discipline → [`docs/agents/AGENT_COLLAB_RUNBOOK.md`](docs/agents/AGENT_COLLAB_RUNBOOK.md)
- Oya (supervisor) behaviour → [`docs/operator/oyakata-prompt-v0.1.md`](docs/operator/oyakata-prompt-v0.1.md)

The rules below are the ones that have actually bitten in past sessions. Each
exists because the failure recurred, not as generic good advice.

## Shell & file content

- **Write file content with the Write/Edit tools, not bash heredocs.** Heredocs
  containing backticks, apostrophes, `$`, or quotes corrupt silently. This is the
  single most recurring source of garbled comms output and `SyntaxWarning`s.
- **Never over-escape `$`.** Inside a single-quoted heredoc or a tool-written
  file, `$` is literal — adding `\$` produces a literal backslash artifact.
- For multi-line comms specifically, the runbook's `### Writing method` rule
  applies: append at true EOF via Python or a write tool, never a heredoc.

## Git

- **A local commit that isn't pushed is not a failed fix.** Before concluding a
  commit or fix is absent, compare local to remote — `git rev-parse HEAD` vs
  `git rev-parse origin/main`, or `git log origin/main..HEAD`. "Not on the
  remote" ≠ "the work failed."
- **Never `git add` an already-deleted path** expecting content to be staged —
  it stages nothing. Check `git status` reflects the intended change before
  committing.
- Don't commit or push unless asked. This is a public repo; sign-off precedes
  any push.

## Testing scripts

- **Run scripts end-to-end before reporting them done.** `bash -n` is a syntax
  check, not a test. Handoff/updater/bootstrap scripts that ship on a syntax
  check alone have carried fixture bugs into colleagues' machines.
- For destructive or stateful scripts, run against a throwaway copy/fork first —
  this is how bootstrap `--force` backup-on-overwrite was verified live.

## Long output

- **Write long deliverables (reports, decks, generated code, multi-tab data) to
  files; give a short summary inline.** Printing them risks output-token
  truncation that wipes the transcript. For tabular deliverables prefer a styled
  `.xlsx` (openpyxl) over CSV — long comma-laden cells break Excel CSV import.
