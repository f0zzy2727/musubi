#!/usr/bin/env bash
# ci-baseline.sh — pre-push CI baseline check.
#
# Surfaces the CI status of the last 5 runs on the main branch so the human
# lead can see whether they're about to approve a push on top of stale red.
#
# Output is designed to be pasted verbatim into the push-approval comms
# message. The script does NOT block — it informs. The runbook's Mechanical
# Gates section defines when @LEAD ack is required (count = 0).
#
# Usage:
#   scripts/ci-baseline.sh [workflow]
#
# Defaults:
#   workflow = ci.yml
#
# Examples:
#   scripts/ci-baseline.sh
#   scripts/ci-baseline.sh tests.yml
#
# Requires: gh (GitHub CLI), authenticated against the repo's remote.

set -euo pipefail

WORKFLOW="${1:-ci.yml}"
BRANCH="main"
LIMIT=5

if ! command -v gh >/dev/null 2>&1; then
  echo "ci-baseline: FAIL — 'gh' (GitHub CLI) not installed." >&2
  echo "  install: https://cli.github.com/  |  brew install gh" >&2
  exit 2
fi

# Count successful runs in the last LIMIT runs on BRANCH.
count=$(gh run list \
  --workflow="$WORKFLOW" \
  --branch "$BRANCH" \
  --limit "$LIMIT" \
  --json conclusion \
  --jq '[.[] | .conclusion] | map(select(. == "success")) | length' 2>/dev/null || echo "0")

# If gh failed entirely (no runs found, no perms, etc.), normalise to 0.
if [ -z "$count" ] || ! [[ "$count" =~ ^[0-9]+$ ]]; then
  count=0
fi

echo "**CI baseline status:** ${count}/${LIMIT} of last ${LIMIT} ${BRANCH} CI runs succeeded"
echo ""

# When there is no green baseline, dump the detail block. The runbook
# requires this block to appear VERBATIM in the push-approval message so
# @LEAD can see exactly what they're about to approve a push on top of.
if [ "$count" -eq 0 ]; then
  echo "Last ${LIMIT} runs on ${BRANCH} (workflow: ${WORKFLOW}):"
  gh run list \
    --workflow="$WORKFLOW" \
    --branch "$BRANCH" \
    --limit "$LIMIT" \
    --json headSha,conclusion,createdAt \
    --jq '.[] | "  \(.headSha[0:8]) \(if .conclusion == "" then "in_progress" else .conclusion end) \(.createdAt[0:10])"' \
    || echo "  (gh run list failed — check authentication and workflow name)"
  echo ""
  echo "This push is either a CI hotfix that should fix it,"
  echo "or @LEAD is explicitly accepting a stale-baseline push."
  echo ""
  echo "Wait for explicit @LEAD ack before pushing."
fi

# Always exit 0 — this is an informational gate, not a blocking one. The
# blocking happens at the human-approval step in the comms protocol.
exit 0
