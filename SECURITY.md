# Security Policy

## Reporting a vulnerability

If you find a security issue in musubi — anything that could allow command execution, credential leakage, or unauthorised access to the host running the orchestrator — please **do not open a public issue**.

Report it privately via GitHub's **"Report a vulnerability"** button on the **Security** tab of this repository (Security → Advisories → Report a vulnerability), or email **info@lugha.ie**. Include:

- A short description of the vulnerability and its impact
- Steps to reproduce (a minimal repro is more useful than a long write-up)
- Your assessment of severity and exploit conditions
- Whether you intend to publish the finding, and your preferred timeline

You will get a response within 5 working days acknowledging receipt. A patched release will follow as quickly as the fix allows; coordinated disclosure is preferred but not required.

## Scope

In scope:

- `orchestrator.py` — command construction, file I/O, tmux session handling
- `bootstrap.sh` and `launch_musubi*.sh` — shell injection, path handling, privilege escalation
- The comms protocol — anything that lets an agent or attacker manipulate the relay or impersonate a peer
- `scripts/guard-staged-scope.sh` and `scripts/ci-baseline.sh` — bypass or false-positive paths that could weaken the mechanical gates

Out of scope:

- Bugs in `libtmux`, `tmux`, Claude Code CLI, or Codex CLI — report those upstream.
- Issues that require the attacker to already have write access to `musubi.toml` on the operator's machine (the config is trusted by design).
- Theoretical attacks against the agents' models themselves (prompt injection of the LLMs) — handled by the model vendors, not by musubi.

## What musubi does and does not protect against

musubi is a coordination harness, not a sandbox. It assumes:

- The operator trusts both AI agents to run shell commands in the project directory.
- The operator reviews the comms file and the agents' work before merge.
- The agents are authenticated against their respective providers; musubi does not handle credentials.

If your threat model requires sandboxing the agents from the host filesystem, musubi is the wrong tool for that layer — pair it with a containerised execution environment.
