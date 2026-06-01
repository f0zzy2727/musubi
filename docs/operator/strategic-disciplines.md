# Strategic disciplines — per-discipline authority

> **v0.3-strategic** (2026-05-20). This is the per-discipline catalogue for strategic-Oya's slice-claim challenge. Sibling to the existing schema docs (`asymmetry-schema.md`, `calibration-schema.md`, `operator-critique-schema.md`, `rules-ledger-schema.md`, `shadow-review-schema.md`).

When the scope sensor (`scripts/classify-slice-disciplines.py`) fires on a slice-claim, Oya cites the triggered discipline by name and posts an `@OYA` Recommendation following the per-discipline shape below. The pair produces the required artefact in the planning doc (catch) or acknowledges and proceeds without it (skip). Both outcomes increment the rules-ledger counters per `rules-ledger-schema.md` § What counts as a skip.

The catalogue's contract:

- **Discipline ID** matches the `citation_pattern` in `templates/rules-ledger.yml.template`.
- **Triggers** is a summary; the authoritative sensor logic is in `classify-slice-disciplines.py` `TRIGGERS` table.
- **Required artefact** is what musubi tracks. Production path is operator-tool-choice (gstack skills, raw prompting, vendor tooling — all equivalent if they yield a conformant artefact).
- **Recommendation template** is what Oya posts to comms. Substitute `{slice-id}`, `{matched-files}`, etc. as appropriate; keep the structure constant so the ledger's citation_pattern remains grep-able.
- **Catch criterion** is what musubi inspects to decide whether the artefact was produced. Honest minimum bars — too-loose lets discipline theatre through; too-strict produces friction.

---

## threat-model-auth-changes

**Triggers:** slice touches auth surfaces — `/auth/`, `/sessions/`, `/tokens/`, `/oauth/`, `/oidc/`, `/saml/`, `/iam/`, password handling, identity-provider configs; planning doc mentions authentication / authorization / session tokens / access tokens / refresh tokens / auth boundary.

**Required artefact:** STRIDE table in the planning doc with at minimum one row for each of: Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege. Each row names the threat in the slice's context + the mitigation (or "out of scope, see X" if delegated upstream).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice acceptance scope includes auth surfaces:
  - {matched-files}

Per discipline `threat-model-auth-changes`: paste a STRIDE table into the
planning doc covering spoofing / tampering / repudiation / information-
disclosure / DoS / elevation-of-privilege. Each row names the threat in
this slice's context and the mitigation (or explicit "out of scope" with
the upstream owner). How you produce the table is your choice.

Skip is allowed: acknowledge and the skip is logged. Cycle proceeds.

<OVER>
```

**Catch criterion:** planning doc contains the six STRIDE class names AND at least four rows have substantive (>1 sentence) content. Token presence alone (table headers with empty rows) is theatre, not catch.

---

## abuse-case-named-on-new-input

**Triggers:** new external input surface — paths matching `/routes/`, `/endpoints/`, `/api/`, `/webhooks/`, `/handlers/`, `/controllers/`; planning doc mentions new route / endpoint / handler / webhook, external input, user-submitted, abuse case.

**Required artefact:** abuse-case list in the planning doc enumerating, per new input field: oversize input, malformed/invalid encoding, injection attempts (SQL / shell / template), replay / idempotency violation, boundary bypass (auth scope, tenant scope, rate-limit bypass). Minimum five named abuse cases per new endpoint.

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice introduces new external input surface:
  - {matched-files}

Per discipline `abuse-case-named-on-new-input`: enumerate the abuse cases
per new input — what happens with oversized / malformed / injected /
replayed / boundary-bypassing inputs? At least five named cases per
endpoint, with the intended response noted. Paste the list into the
planning doc.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc contains an "Abuse cases" or equivalently-named section listing ≥5 named cases AND each case names a specific input field or interaction shape (not generic).

---

## migration-has-rollback-plan

**Triggers:** schema migration / data-model change — paths matching `/migrations/`, `/schema/`, `*.sql`, `prisma/schema`, `alembic/versions`; planning doc mentions schema change, data model migration, ALTER/CREATE/DROP TABLE, rollback plan.

**Required artefact:** rollback plan in planning doc covering: the inverse migration (script or steps), data-loss assessment (which rows or columns become unrecoverable), lock-contention assessment (what's locked during reversal, for how long), safe-rollback window (is there a point-of-no-return?). Minimum: a 3–5 step reversal procedure.

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice modifies the schema / data model:
  - {matched-files}

Per discipline `migration-has-rollback-plan`: before applying, paste a
rollback plan into the planning doc — the inverse migration steps,
data-loss assessment, lock-contention assessment, and the point of no
return. Minimum 3–5 step reversal procedure.

Skip is allowed: acknowledge and the skip is logged. Cycle proceeds.

<OVER>
```

**Catch criterion:** planning doc contains a "Rollback" or "Reversal plan" section with ≥3 numbered steps AND at least one explicit named risk (data loss / lock contention / irreversible after X).

---

## idempotency-on-money-handling

**Triggers:** payment / billing / money-handling — paths matching `/payments/`, `/billing/`, `/checkout/`, `/invoice`, `/stripe/`, `/square/`, `/paypal/`; planning doc mentions payment, charge, refund, invoice, idempotency, reconciliation.

**Required artefact:** idempotency contract in planning doc naming: the dedup key (what makes two requests "the same"), the storage layer for dedup state (DB table, Redis key, vendor-side), the time-to-live for dedup (when can the same key be reused?), the audit log location (where every money-affecting event is recorded), the reconciliation path (how do we detect double-charges after the fact?).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice touches money-handling surfaces:
  - {matched-files}

Per discipline `idempotency-on-money-handling`: paste the idempotency
contract into the planning doc — dedup key, dedup storage, dedup TTL,
audit log location, reconciliation path. What protects against double-
charges on network retry? Paste explicit answers, not assurances.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc names ALL of: dedup key + storage + audit log location. Reconciliation path is bonus but not required (some systems delegate to vendor reconciliation).

---

## a11y-check-on-ui-slice

**Triggers:** user-facing UI surface — files matching `.tsx`, `.jsx`, `.vue`, `.svelte`; paths in `/pages/`, `/views/`, `/components/`; planning doc mentions user-facing, new page/form/flow/screen/dashboard, WCAG, accessibility, a11y.

**Required artefact:** a11y check list in planning doc covering at minimum: keyboard navigation (tab order, escape, enter behaviour), colour contrast (text vs background, against WCAG 2.1 AA ratio 4.5:1), screen-reader labels (aria-label / aria-describedby / semantic HTML used), focus states (visible focus ring, focus management on dynamic content). Bonus: motion / animation preferences, error message accessibility, form validation announcements.

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice touches user-facing UI:
  - {matched-files}

Per discipline `a11y-check-on-ui-slice`: paste the a11y check list into
the planning doc — keyboard navigation, colour contrast (WCAG 2.1 AA),
screen-reader labels, focus states. Either name the checks performed
OR the explicit reason a check doesn't apply for this slice.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc names ≥4 of the listed checks AND each named check has an outcome (passed / failed / not-applicable with reason). "Will check later" is theatre, not catch.

---

## external-integration-failure-mode

**Triggers:** external/third-party integration — paths in `/integrations/`, `/vendors/`, `/clients/*-client/`; planning doc mentions third-party API/SDK/service, external API/service/vendor, vendor SDK, upstream down/failure/outage, retry-backoff.

**Required artefact:** failure-mode contract in planning doc covering: upstream-down behaviour (do we fail-open / fail-closed / degrade?), latency budget (what's the timeout? what triggers it?), retry policy (max attempts, backoff shape, idempotency interaction), rate-limit handling (what happens when we hit vendor limits?), API change tolerance (what breaks if vendor changes response shape?), circuit-breaker shape (open / half-open / closed transitions).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice introduces an external integration:
  - {matched-files}

Per discipline `external-integration-failure-mode`: paste the failure-mode
contract into the planning doc — upstream-down behaviour, latency budget,
retry policy, rate-limit handling, API-change tolerance. Name what
degrades when the vendor degrades.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc names ≥3 of: upstream-down behaviour, retry policy, latency budget, rate-limit handling. Each named with specifics (not "we retry on failure" — "max 3 retries, exponential backoff capped at 10s, ignore on 4xx").

---

## ai-integration-design-contract

**Triggers:** AI feature surface — paths in `/llm/`, `/ai/`, `/prompts/`, `/embeddings/`, `/rag/`, `/agents/`, vendor-named integrations (anthropic-*, openai-*, langchain, llamaindex, cohere); planning doc mentions LLM, prompt engineering/template, embeddings, RAG, AI feature/integration/model, claude-N/gpt-N/gemini-N, evaluation set, guardrails, `import anthropic` / `import openai` patterns.

**Required artefact:** AI-SPEC in planning doc covering at minimum: one eval case (specific input + expected output / acceptance criterion), one named guardrail (prompt-injection defence / output validation / refusal boundary), one monitored production signal (latency / cost / eval pass rate / drift indicator), model-swap blast radius (what changes if the model is deprecated or behaviour drifts).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice introduces or modifies AI integration:
  - {matched-files}

Per discipline `ai-integration-design-contract`: paste an AI-SPEC into
the planning doc — at minimum: one eval case, one named guardrail,
one monitored production signal, model-swap blast radius. Without an
eval, "does it work?" gets answered by happy-path manual testing.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc contains an AI-SPEC section with all four minimum elements present (1 eval, 1 guardrail, 1 signal, model-swap note). See [[ai-1]] in IA-QUEUE.md for the longer-form discipline rationale.

---

## pii-inventory-on-data-change

**Triggers:** user-data / PII handling — paths matching `/users/*.(ts|tsx|py|rs|go|js)`, `/profile/`, `/personal-data/`; planning doc mentions PII, personal data/information, user data/profile/account, GDPR, data deletion/retention.

**Required artefact:** PII inventory in planning doc listing: the user-data fields touched in this slice (column / property names), the retention rule for each (forever, N days, on-account-deletion, etc.), the deletion path (how is this data removed when a user requests deletion?), the access controls (who can read this field — tenant-scoped, admin-only, public).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice modifies user-data / PII handling:
  - {matched-files}

Per discipline `pii-inventory-on-data-change`: paste the PII inventory
into the planning doc — fields touched, retention rules, deletion path,
access controls. GDPR/privacy posture must be intentional, not accidental.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc lists the touched fields by name AND names a retention rule AND a deletion path for each. Generic "PII handled per GDPR" is theatre.

---

## observability-on-user-facing

**Triggers:** user-facing endpoints / flows — paths matching `/api/*.(ts|js|py)`, `/handlers/`; planning doc mentions observability, monitoring contract, logging discipline, SLO, SLI, production monitoring.

**Required artefact:** observability contract in planning doc covering: structured-log fields emitted (what's the line on success / failure?), metrics emitted (counter / histogram / gauge name + dimensions), the SLI (what number measures "this is working in production?"), the alert (what fires when the SLI breaches, who gets paged), the dashboard location (where does a human go to debug this in prod?).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice introduces or modifies a user-facing surface:
  - {matched-files}

Per discipline `observability-on-user-facing`: paste the observability
contract into the planning doc — structured logs, metrics, SLI, alert,
dashboard location. What metric tells us this is broken in production?

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc names AT LEAST: structured-log fields, one metric, one SLI. Alert + dashboard are bonus (some teams centralize these).

---

## arch-sketch-before-large-slice

**Triggers:** size-based — slice diff exceeds 300 LOC OR touches more than 3 files. This is the only discipline that fires on size alone, not pattern.

**Required artefact:** arch sketch in planning doc covering: module boundaries (what's the slice's outer interface?), data-flow diagram or description (where does state enter, transform, exit?), at least 3 named failure modes (what can go wrong, and what's the blast radius), test strategy (what's the proof-of-correctness shape — unit / integration / smoke / visual / E2E?).

**Recommendation template:**

```
[@OYA] [YYYY-MM-DD] [HH:MM UTC]
To: @<claiming agent>
Reply required: yes
GO: no
Type: Recommendation

Slice exceeds size threshold:
  - {matched-files} ({file-count} files, {loc} LOC)

Per discipline `arch-sketch-before-large-slice`: paste an arch sketch
into the planning doc before coding — module boundaries, data flow,
≥3 named failure modes, test strategy. Don't start until the sketch
is on disk. The pair's review depth is bounded by what was on paper
before the code.

Skip is allowed: acknowledge and the skip is logged.

<OVER>
```

**Catch criterion:** planning doc names module boundaries AND data flow AND ≥3 failure modes. Test strategy is bonus.

---

## Two intervention points — slice-claim vs pre-push

Strategic-Oya intervenes at TWO cycle-time moments. The disciplines above are the same; the question Oya asks differs.

| | Slice-claim challenge | Pre-push red team |
|---|---|---|
| **Trigger** | `Type: Update` / `Result: claimed` | `Type: Review Request` or push-approval request |
| **Input** | Stated intent — planning doc + acceptance receipt scope | Actual delivered scope — `git diff` against slice base |
| **Question** | *"Did you think about X before coding?"* | *"Now that you've written it, what does it not handle?"* |
| **Posting type** | Recommendation (GO: no — informational, before code) | Note (GO: yes — advisory, doesn't gate push) |
| **Outcome counts** | Catch (artefact present) / Skip (artefact missing) | Addressed (probe resolved) / Acknowledged (probe ignored but logged) |
| **Cap** | One Recommendation per triggered discipline | ≤ 3 probes per pre-push |
| **Authority** | Forgiving advisory; pair can skip | Forgiving advisory; pair can ignore |

A slice can:
- **Catch the challenge AND survive the probe** → clean. The artefact anticipated what shipped.
- **Catch the challenge AND fail the probe** → artefact was theatre; the diff went beyond what the artefact covered. Cycle-close downgrades the catch to skip.
- **Skip the challenge AND survive the probe** → forgiving authority worked. The pair judged the discipline didn't apply and was right.
- **Skip the challenge AND fail the probe** → expected. Pair skipped the discipline; probe surfaces what they're shipping without coverage. Operator decides.

The red-team's job is the judgement layer no sensor can mechanize. The disciplines above tell the pair *what to think about*; the red team tells them *what they specifically missed*. Same senior-engineer role, different temporal vantage point.

## On false positives

The scope sensor is a v1. False positives WILL happen — a slice triggers a discipline that wouldn't have warranted it under a senior engineer's read.

The forgiving authority shape handles this gracefully: the pair (or operator) skips, the skip is logged, the cycle proceeds. **A skip is not a defect**.

But persistent false-positive patterns ARE a sensor-refinement signal. If `a11y-check-on-ui-slice` keeps firing on `.tsx` files that are pure server-component logic without rendered output, the trigger pattern is too coarse. File an I&A item against `scripts/classify-slice-disciplines.py` `TRIGGERS` table (not against the discipline rule itself — the rule name and its artefact contract stay stable).

## On false negatives

The harder case: a slice DIDN'T fire any discipline but a senior engineer would have flagged something.

Oya can still log a `MEDIUM` observation in `oyakata-log.md` naming the discipline she'd have wanted to apply, with a note that the sensor missed it. At cycle close this becomes a `silent_misses.examples` entry on the relevant rule + an I&A candidate for the sensor.

The sensor's job is mechanical pattern-match. Oya's job is to notice when the mechanical version was wrong.

## On adding new disciplines

The v0.3 set (10 disciplines) is a v1 codification of what a senior engineer brings to a code review. It's incomplete by design. Plausible additions surfaced by operating experience:

- **`secrets-handling-on-config-change`** — slice touches `.env`, secrets files, vault clients
- **`migration-window-on-deploy-affecting`** — slice affects deploy flow, rolling restart, blue/green
- **`backwards-compat-on-public-api-change`** — slice modifies an externally-consumed contract
- **`load-shedding-on-hot-path`** — slice in a known-hot-path; capacity / circuit-breaker discipline

Don't add these speculatively. Add them when the rules-ledger surfaces a pattern of silent_misses where these disciplines would have caught something. Same evidence discipline the framework requires of itself: rules earn their way in.

## See also

- `scripts/classify-slice-disciplines.py` — sensor implementation; trigger logic authority
- `templates/rules-ledger.yml.template` — ledger seed entries for all 10 disciplines
- `oyakata-prompt-v0.1.md` § Slice-claim challenge — mechanism Oya executes
- `rules-ledger-schema.md` § What counts as a skip — counter semantics
