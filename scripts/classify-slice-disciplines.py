#!/usr/bin/env python3
"""classify-slice-disciplines.py — scope sensor for strategic-Oya v0.3.

Reads a slice's touched files + optional planning-doc text + LOC count,
and outputs the engineering disciplines a senior engineer would flag for
review on this slice. Standalone CLI; no musubi orchestrator coupling.

Future consumer (Slice 3+): the Oya prompt will call this at slice-claim
and pre-push events, then surface the triggered disciplines as `@OYA`
Notes — "this slice touches auth surfaces; threat-model the change before
code begins."

Output format:
  --format text (default) — human-scannable summary with evidence trail
  --format json           — machine-consumable for Oya / tooling

Invocation:
  classify-slice-disciplines.py --files src/auth/session.ts src/api/route.ts
  classify-slice-disciplines.py --files-from <(git diff --name-only HEAD~1)
  classify-slice-disciplines.py --files src/x.ts --planning-doc plans/slice-a.md --loc 247
  cat plans/slice-a.md | classify-slice-disciplines.py --files src/x.ts --planning-doc-stdin

Exit codes:
  0  triggered disciplines printed (or none if no triggers fired)
  2  invalid arguments / no input

This is Slice 2 of the v0.3-strategic build. See IA-QUEUE.md item
`oyakata-3` for the full spec. The trigger table here is a v1 — refined
by the rules-ledger evidence after a few real cycles surface false
positives (over-firing) and false negatives (missed slices).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Trigger table — the framework's v1 codification of "which disciplines apply
# to which slice classes." Each entry has:
#   discipline       — the runbook rule name (citation_pattern for ledger)
#   path_patterns    — regex against any touched file path (case-insensitive)
#   content_patterns — regex against planning-doc text (case-insensitive)
#   summary          — one-line operator-facing description of the trigger
# A discipline fires if ANY of its path or content patterns matches.
# ---------------------------------------------------------------------------

@dataclass
class Trigger:
    discipline: str
    summary: str
    path_patterns: tuple = ()
    content_patterns: tuple = ()


TRIGGERS = [
    Trigger(
        discipline="threat-model-auth-changes",
        summary="auth / session / token / identity-provider surface touched",
        path_patterns=(
            r"/auth(/|\b)",
            r"/sessions?(/|\b)",
            r"/tokens?(/|\b)",
            r"/oauth(/|\b)",
            r"/oidc(/|\b)",
            r"/saml(/|\b)",
            r"/iam(/|\b)",
            r"password",
            r"identity[-_]?provider",
        ),
        content_patterns=(
            r"\bauthentic(ate|ation)\b",
            r"\bauthoriz(e|ation)\b",
            r"\bsession[-_ ]?(token|cookie)\b",
            r"\baccess[-_ ]?token\b",
            r"\brefresh[-_ ]?token\b",
            r"\bauth[-_ ]?boundary\b",
        ),
    ),
    Trigger(
        discipline="abuse-case-named-on-new-input",
        summary="new external input surface (route, endpoint, webhook, handler)",
        path_patterns=(
            r"/routes?(/|\b)",
            r"/endpoints?(/|\b)",
            r"/api(/|\b)",
            r"/webhooks?(/|\b)",
            r"/handlers?(/|\b)",
            r"/controllers?(/|\b)",
        ),
        content_patterns=(
            r"\bnew\s+(route|endpoint|handler|webhook)\b",
            r"\bexternal\s+input\b",
            r"\buser[-_ ]submitted\b",
            r"\babuse\s+case\b",
        ),
    ),
    Trigger(
        discipline="migration-has-rollback-plan",
        summary="schema migration or data-model change",
        path_patterns=(
            r"/migrations?(/|\b)",
            r"/schema(/|\b)",
            r"db/migrate",
            r"\.sql$",
            r"prisma/schema",
            r"alembic/versions",
        ),
        content_patterns=(
            r"\bschema\s+(change|migration)\b",
            r"\bdata\s+model\s+(change|migration)\b",
            r"\bALTER\s+TABLE\b",
            r"\bCREATE\s+TABLE\b",
            r"\bDROP\s+TABLE\b",
            r"\brollback\s+plan\b",
        ),
    ),
    Trigger(
        discipline="idempotency-on-money-handling",
        summary="payment / billing / money-handling surface",
        path_patterns=(
            r"/payments?(/|\b)",
            r"/billing(/|\b)",
            r"/checkout(/|\b)",
            r"/invoice",
            r"/stripe(/|\b)",
            r"/square(/|\b)",
            r"/paypal(/|\b)",
        ),
        content_patterns=(
            r"\bpayment(s)?\b",
            r"\bcharge(s|d)?\b",
            r"\brefund(s|ed)?\b",
            r"\binvoice(s|d)?\b",
            r"\bidempotenc(y|e)\b",
            r"\breconciliation\b",
        ),
    ),
    Trigger(
        discipline="a11y-check-on-ui-slice",
        summary="user-facing UI surface (page, form, component, view)",
        path_patterns=(
            r"\.(tsx|jsx|vue|svelte)$",
            r"/pages?(/|\b)",
            r"/views?(/|\b)",
            r"/components?(/|\b)",
            r"/app/.*\.(tsx|jsx)$",
        ),
        content_patterns=(
            r"\buser[-_ ]facing\b",
            r"\bnew\s+(page|form|flow|screen|dashboard)\b",
            r"\bWCAG\b",
            r"\baccessibilit(y|e)\b",
            r"\ba11y\b",
        ),
    ),
    Trigger(
        discipline="external-integration-failure-mode",
        summary="external/third-party API or vendor SDK integration",
        path_patterns=(
            r"/integrations?(/|\b)",
            r"/vendors?(/|\b)",
            r"/clients?(/|\b).*[-_]client",
        ),
        content_patterns=(
            r"\bthird[- ]party\s+(api|sdk|service)\b",
            r"\bexternal\s+(api|service|vendor)\b",
            r"\bvendor\s+sdk\b",
            r"\bupstream\s+(down|failure|outage)\b",
            r"\bretry[-_ ]?backoff\b",
        ),
    ),
    Trigger(
        discipline="ai-integration-design-contract",
        summary="LLM / embedding / RAG / agent / prompt surface",
        path_patterns=(
            r"/llms?(/|\b)",
            r"/ai(/|\b)",
            r"/prompts?(/|\b)",
            r"/embeddings?(/|\b)",
            r"/rag(/|\b)",
            r"/agents?(/|\b)",
            r"/(anthropic|openai|langchain|llamaindex|cohere)[-_]",
        ),
        content_patterns=(
            r"\bLLM\b",
            r"\bprompt[-_ ]?(engineering|template)\b",
            r"\bembedding[s]?\b",
            r"\bRAG\b",
            r"\bAI\s+(feature|integration|model)\b",
            r"\b(claude|gpt|gemini)[-_]\d",
            r"\bevaluat(e|ion)\s+set\b",
            r"\bguardrail[s]?\b",
            r"import\s+anthropic\b",
            r"import\s+openai\b",
            r"from\s+anthropic\b",
            r"from\s+openai\b",
        ),
    ),
    Trigger(
        discipline="pii-inventory-on-data-change",
        summary="user-data / PII handling surface",
        path_patterns=(
            r"/users?(/|\b).*\.(ts|tsx|py|rs|go|js)$",
            r"/profile(/|\b)",
            r"/personal[-_]data",
        ),
        content_patterns=(
            r"\bPII\b",
            r"\bpersonal\s+(data|information)\b",
            r"\buser\s+(data|profile|account)\b",
            r"\bGDPR\b",
            r"\bdata\s+(deletion|retention)\b",
        ),
    ),
    Trigger(
        discipline="observability-on-user-facing",
        summary="user-facing endpoint or flow without explicit observability contract",
        path_patterns=(
            # Same path triggers as a11y; the discipline is different
            # (observability vs accessibility), so it fires alongside.
            r"/api(/|\b).*\.(ts|js|py)$",
            r"/handlers?(/|\b)",
        ),
        content_patterns=(
            r"\bobservabilit(y|e)\b",
            r"\bmonitoring\s+contract\b",
            r"\blogging\s+discipline\b",
            r"\bSLO\b",
            r"\bSLI\b",
            r"\bproduction\s+monitoring\b",
        ),
    ),
]


# Size triggers fire on absolute thresholds (not pattern-matched).
ARCH_SKETCH_LOC_THRESHOLD = 300
ARCH_SKETCH_FILE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

@dataclass
class TriggerHit:
    discipline: str
    summary: str
    evidence: list = field(default_factory=list)


def _find_path_matches(pattern, files):
    """Return list of paths matching a regex (case-insensitive)."""
    rx = re.compile(pattern, re.IGNORECASE)
    return [f for f in files if rx.search(f)]


def _find_content_matches(pattern, planning_doc):
    """Return list of distinct line snippets matching a regex in the planning
    doc (case-insensitive). Capped at 3 snippets per pattern to keep evidence
    trails scannable."""
    if not planning_doc:
        return []
    rx = re.compile(pattern, re.IGNORECASE)
    out = []
    seen = set()
    for line in planning_doc.splitlines():
        if rx.search(line):
            snippet = line.strip()[:100]
            if snippet and snippet not in seen:
                seen.add(snippet)
                out.append(snippet)
                if len(out) >= 3:
                    break
    return out


def classify(files=None, planning_doc=None, loc=None):
    """Return list of TriggerHit for all disciplines that fired on this slice.

    Args:
        files: list of touched file paths (relative or absolute, all matched
               case-insensitively against the trigger path patterns)
        planning_doc: optional planning-doc text content
        loc: optional total LOC of the slice's diff (for arch-sketch trigger)

    A discipline fires if ANY of its path patterns match a touched file OR ANY
    of its content patterns match a planning-doc line. The TriggerHit's
    `evidence` field lists which pattern(s) matched and where, so the operator
    can see WHY the discipline fired (not just THAT it did).
    """
    files = files or []
    hits = []

    for trigger in TRIGGERS:
        evidence = []

        for pat in trigger.path_patterns:
            matched_files = _find_path_matches(pat, files)
            for f in matched_files:
                evidence.append(f"path: {f} (matched /{pat}/)")

        for pat in trigger.content_patterns:
            matched_lines = _find_content_matches(pat, planning_doc)
            for line in matched_lines:
                evidence.append(f"planning doc: {line!r} (matched /{pat}/)")

        if evidence:
            hits.append(TriggerHit(
                discipline=trigger.discipline,
                summary=trigger.summary,
                evidence=evidence,
            ))

    # Size-based trigger: arch-sketch-before-large-slice
    file_count = len(files)
    size_evidence = []
    if loc is not None and loc > ARCH_SKETCH_LOC_THRESHOLD:
        size_evidence.append(f"diff size: {loc} LOC (> {ARCH_SKETCH_LOC_THRESHOLD} threshold)")
    if file_count > ARCH_SKETCH_FILE_THRESHOLD:
        size_evidence.append(f"file count: {file_count} (> {ARCH_SKETCH_FILE_THRESHOLD} threshold)")
    if size_evidence:
        hits.append(TriggerHit(
            discipline="arch-sketch-before-large-slice",
            summary="slice exceeds size threshold — arch sketch + named failure modes required",
            evidence=size_evidence,
        ))

    return hits


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_text(hits, files, planning_doc, loc):
    lines = []
    lines.append("=== Slice discipline classification ===")
    lines.append(f"Files examined: {len(files)}")
    if loc is not None:
        lines.append(f"LOC examined: {loc}")
    lines.append(f"Disciplines triggered: {len(hits)}")
    lines.append("")
    if not hits:
        lines.append("No disciplines triggered. Either the slice is genuinely light,")
        lines.append("or the trigger table missed something a senior engineer would have flagged.")
        lines.append("If the latter, file an I&A item against the trigger sensor.")
        return "\n".join(lines)
    for hit in hits:
        lines.append(f"• {hit.discipline}")
        lines.append(f"  {hit.summary}")
        for ev in hit.evidence[:5]:  # cap evidence in text mode
            lines.append(f"    - {ev}")
        if len(hit.evidence) > 5:
            lines.append(f"    - ... ({len(hit.evidence) - 5} more)")
        lines.append("")
    return "\n".join(lines)


def format_json(hits, files, planning_doc, loc):
    return json.dumps({
        "summary": {
            "files_examined": len(files),
            "loc_examined": loc,
            "disciplines_triggered": len(hits),
        },
        "triggers": [asdict(h) for h in hits],
    }, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_files_arg(args):
    if args.files_from:
        with open(args.files_from) as f:
            return [line.strip() for line in f if line.strip()]
    return list(args.files or [])


def _read_planning_doc(args):
    if args.planning_doc_stdin:
        return sys.stdin.read()
    if args.planning_doc:
        with open(args.planning_doc) as f:
            return f.read()
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Classify a slice's triggered engineering disciplines."
    )
    parser.add_argument("--files", nargs="*", help="touched file paths")
    parser.add_argument("--files-from", help="read file paths from this file (one per line)")
    parser.add_argument("--planning-doc", help="path to slice planning doc")
    parser.add_argument("--planning-doc-stdin", action="store_true",
                        help="read planning doc from stdin")
    parser.add_argument("--loc", type=int, help="total LOC of the slice's diff")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="output format (default: text)")
    args = parser.parse_args(argv)

    files = _read_files_arg(args)
    planning_doc = _read_planning_doc(args)
    if not files and not planning_doc:
        parser.error("must provide --files, --files-from, --planning-doc, or --planning-doc-stdin")

    hits = classify(files=files, planning_doc=planning_doc, loc=args.loc)
    if args.format == "json":
        print(format_json(hits, files, planning_doc, args.loc))
    else:
        print(format_text(hits, files, planning_doc, args.loc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
