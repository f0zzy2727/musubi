#!/usr/bin/env python3
"""comms-metrics.py — quantitative collaboration metrics over musubi comms logs.

Implements Track 1 of the benchmarking plan in
docs/positioning/collaboration-sophistication-and-benchmarks-2026-06.md:
mechanical + role-divergence (SEI) + closed-loop + evidence-discipline metrics,
scored over the structured comms corpus, per codebase and per speaker.

These are MARL/LLM-MAS-adapted proxies computed from message structure — not
LLM-judged. The LLM-judged tracks (MARBLE Communication Score, NOTECHS coding)
are separate. Every metric here is deterministic and reproducible.

Usage:
    python3 scripts/comms-metrics.py <comms_dir> [<comms_dir> ...] [--json out.json]

A comms_dir is a `docs/agents` directory; the script finds archive/*.txt|*.md
and comms/active.txt under it.
"""
import sys, os, re, json, math
from collections import Counter, defaultdict

# A turn header looks like:  [@OPUS] [2026-06-09] [09:18 UTC]
HEADER = re.compile(r'^\[@?([A-Z][A-Z0-9_]+)\]\s*\[([0-9]{4}-[0-9]{2}-[0-9]{2})\]\s*\[([^\]]+)\]')
TYPE   = re.compile(r'^Type:\s*(.+?)\s*$', re.I)
GO     = re.compile(r'^GO:\s*(\w+)', re.I)
# Slice id, echoed by the contested-debate protocol so review turns can be
# grouped into exchanges (forced-debate measurement). `Slice: <id>` on its line.
SLICE  = re.compile(r'^Slice:\s*(\S.+?)\s*$', re.I)
WORD   = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")
# receipt signatures: git SHAs, file:line, commands, exit codes
SHA    = re.compile(r'\b[0-9a-f]{7,40}\b')
FILELINE = re.compile(r'[\w./-]+\.\w+:\d+')
# closed-loop acknowledgment: a message that reads back / confirms a prior turn
ACK    = re.compile(r'\b(Read @|Read the|Read your|independently (?:checked|verified|re-?ran|traced)|confirms?\b|confirmed\b|acknowledg|per @\w+\'s|per your)', re.I)
# reviewer surfaced a substantive issue (proxy for INDEPENDENT-CATCH:
# reviewer found something the author missed)
FINDING = re.compile(r'(changes[_ -]?requested|blocking finding|\bobjection\b|falsif|\bfindings?\b|did not (?:pass|approve)|will not approve|must (?:fix|reconcile|address))', re.I)
# both-agents-missed-it, caught later by CI/human/restart (proxy for CORRELATED-MISS:
# the failure mode heterogeneity is supposed to guard against)
ESCAPE  = re.compile(r'(review[- ]escape|peer[- ]review escape|both .{0,40}approved|neither .{0,30}(?:caught|saw|found)|slipped past|CI caught|caught by CI|escaped (?:both|review)|missed by both)', re.I)
# --- convergence-quality (premature-consensus proxy) ------------------------
# Deterministic version of the Track-2 hand-rated "premature consensus" number,
# keyed on what real Review RESULT messages actually contain (the formal
# `changes_requested` token is near-unused: ~2 vs ~900 approves across beds, so
# it can't be the sole signal). A Review Result is classed as:
#   dissent     — explicit non-approve verdict (the rare, strongest contested signal)
#   substantive — ≥1 positive finding in the Findings block (reviewer caught a real
#                 defect/risk, even if it ultimately approved → a genuine round)
#   clean       — approve with zero substantive findings (rubber-stamp-SHAPED)
# A finding bullet is positive when it says `found` (incl. found-RISK/-defect) and
# is NOT a `not-found` / `ruled out` / `N/A` negative.
#
# SCOPE LIMIT (honest): this is a per-MESSAGE signal, not the exchange-level
# "converged in ≤1 exchange" number the design doc asks for. A clean approve can
# be the FINAL turn of a genuine multi-round debate — without a slice identity to
# group turns, this metric cannot tell "approved after 3 rounds" from "approved on
# sight". Exchange-level convergence needs a `Slice:` grouping key in the comms
# protocol (deferred — it's a behaviour change). Read `zero_finding_approve_rate`
# as "fraction of verdicts that are rubber-stamp-shaped", a CEILING on premature
# consensus, not the rate itself.
# Verdict-specific only: bare `reject`/`blocking` are code vocabulary in app
# comms (Promise.reject, rejectWithValue, non-blocking) and wildly over-match —
# keep this to phrases that only occur in a review VERDICT.
FORMAL_DISSENT = re.compile(r'changes[_ -]?requested|not confident|not[- ]verified|will not approve|changes[- ]required|do not (?:ship|merge)', re.I)
_NEG_FINDING   = re.compile(r'not[- ]found|ruled out|\bn/?a\b', re.I)


def classify_review_result(body):
    """Return 'dissent' | 'substantive' | 'clean' for a Review Result body."""
    if FORMAL_DISSENT.search(body):
        return 'dissent'
    for ln in body.splitlines():
        s = ln.strip()
        if not s.startswith('-'):
            continue
        low = s.lower()
        if _NEG_FINDING.search(low):
            continue
        if 'found' in low or 'defect' in low:
            return 'substantive'
    return 'clean'

BOILER_KEYS = ('Subject:', 'Reply required:', 'GO:', 'GO owner:', 'GO action:')
SECTION_KEYS = ('Action:', 'Evidence:', 'Result:', 'Next:', 'Restate')

CODERS = {'OPUS', 'CODA', 'CODEX'}  # the peer-pair handles


def find_files(d):
    out = []
    for root, _, fs in os.walk(d):
        if '/.git/' in root:
            continue
        for f in fs:
            if f.endswith('.lock'):
                continue
            if ('comms' in f.lower() or f == 'active.txt') and (f.endswith('.txt') or f.endswith('.md')):
                out.append(os.path.join(root, f))
    return out


def parse_messages(text):
    """Split a comms file into messages keyed by the [@SPEAKER] [date] [time] header."""
    lines = text.splitlines()
    msgs = []
    cur = None
    for ln in lines:
        m = HEADER.match(ln.strip())
        if m:
            if cur:
                msgs.append(cur)
            cur = {'speaker': m.group(1), 'date': m.group(2), 'time': m.group(3),
                   'type': None, 'go': None, 'slice': None, 'body': [], 'raw': [ln]}
            continue
        if cur is None:
            continue
        cur['raw'].append(ln)
        t = TYPE.match(ln.strip())
        if t and cur['type'] is None:
            cur['type'] = t.group(1)
        g = GO.match(ln.strip())
        if g and cur['go'] is None:
            cur['go'] = g.group(1).lower()
        sl = SLICE.match(ln.strip())
        if sl and cur['slice'] is None:
            cur['slice'] = sl.group(1)
        cur['body'].append(ln)
    if cur:
        msgs.append(cur)
    return msgs


def js_divergence(p, q):
    """Jensen-Shannon divergence between two word-frequency Counters (bits)."""
    vocab = set(p) | set(q)
    if not vocab:
        return 0.0
    ps, qs = sum(p.values()) or 1, sum(q.values()) or 1
    def H(dist):
        return -sum(v * math.log2(v) for v in dist if v > 0)
    pv = [p.get(w, 0)/ps for w in vocab]
    qv = [q.get(w, 0)/qs for w in vocab]
    mv = [(a+b)/2 for a, b in zip(pv, qv)]
    return H(mv) - (H(pv) + H(qv))/2


def analyze(files):
    msgs = []
    over = 0
    rev_req = rev_res = 0
    for f in files:
        try:
            txt = open(f, errors='ignore').read()
        except Exception:
            continue
        over += txt.count('<OVER>')
        rev_req += len(re.findall(r'(?i)review[_ -]?request', txt))
        rev_res += len(re.findall(r'(?i)review[_ -]?result', txt))
        msgs.extend(parse_messages(txt))

    by_speaker = defaultdict(list)
    for m in msgs:
        by_speaker[m['speaker']].append(m)

    speaker_words = defaultdict(Counter)
    type_dist = Counter()
    go_yes = ack_n = ev_n = receipt_n = 0
    review_msgs = review_findings = escape_n = 0
    rr_total = rr_clean = rr_subst = rr_dissent = 0
    slice_review_classes = defaultdict(list)  # slice id -> [class, ...] for review results
    total_tokens = boiler_tokens = section_tokens = 0

    for m in msgs:
        body = '\n'.join(m['body'])
        words = WORD.findall(body.lower())
        speaker_words[m['speaker']].update(words)
        total_tokens += len(words)
        if m['type']:
            type_dist[m['type'].split()[0] if m['type'] else '?'] += 1
        if m['go'] == 'yes':
            go_yes += 1
        if ACK.search(body):
            ack_n += 1
        if 'Evidence:' in body:
            ev_n += 1
        if SHA.search(body) or FILELINE.search(body):
            receipt_n += 1
        is_review = bool(m['type'] and m['type'].lower().startswith('review'))
        if is_review:
            review_msgs += 1
            if FINDING.search(body):
                review_findings += 1
        # Convergence quality is measured on review RESULTS (verdicts), not requests.
        if m['type'] and 'result' in m['type'].lower():
            rr_total += 1
            cls = classify_review_result(body)
            if cls == 'dissent':
                rr_dissent += 1
            elif cls == 'substantive':
                rr_subst += 1
            else:
                rr_clean += 1
            if m['slice']:
                slice_review_classes[m['slice']].append(cls)
        if ESCAPE.search(body):
            escape_n += 1
        for ln in m['body']:
            s = ln.strip()
            toks = len(WORD.findall(s))
            if any(s.startswith(k) for k in BOILER_KEYS):
                boiler_tokens += toks
            if any(s.startswith(k) for k in SECTION_KEYS):
                section_tokens += toks

    # redundancy / communication hygiene: exact-duplicate message bodies
    # (catches triple-posting from append/EOF failures) + near-dup consecutive
    # same-speaker messages (acknowledgement spam)
    def norm(m):
        return re.sub(r'\s+', ' ', '\n'.join(m['body'])).strip().lower()
    bodies = [norm(m) for m in msgs if norm(m)]
    body_counts = Counter(bodies)
    dup_msgs = sum(c-1 for c in body_counts.values() if c > 1)  # extra copies
    consec_dup = 0
    for i in range(1, len(msgs)):
        if msgs[i]['speaker'] == msgs[i-1]['speaker']:
            a, b = norm(msgs[i]), norm(msgs[i-1])
            if a and b:
                wa, wb = set(WORD.findall(a)), set(WORD.findall(b))
                if wa and wb and len(wa & wb) / len(wa | wb) > 0.8:
                    consec_dup += 1

    # Exchange-level convergence (forced-debate target metric). Needs `Slice:`
    # tags to group review turns; degrades to None when the corpus has none (the
    # contested-debate spike isn't running on this bed yet). A slice is CONTESTED
    # if any of its review results raised a real finding or dissent; of those,
    # single-exchange = resolved in exactly one review turn (the premature-
    # consensus signal the per-message rate could only ceiling).
    contested_slices = [s for s, cs in slice_review_classes.items()
                        if any(c in ('substantive', 'dissent') for c in cs)]
    single_exchange = [s for s in contested_slices if len(slice_review_classes[s]) == 1]
    if contested_slices:
        single_exchange_rate = round(len(single_exchange)/len(contested_slices), 3)
        multi_round_rate = round(1 - len(single_exchange)/len(contested_slices), 3)
    else:
        single_exchange_rate = multi_round_rate = None

    n = len(msgs) or 1
    # SEI / role differentiation: JS divergence between the two coders' vocab
    coder_keys = [s for s in by_speaker if s in CODERS]
    sei = None
    if len(coder_keys) >= 2:
        # use the two highest-volume coders
        coder_keys.sort(key=lambda s: -len(by_speaker[s]))
        a, b = coder_keys[0], coder_keys[1]
        sei = round(js_divergence(speaker_words[a], speaker_words[b]), 4)

    return {
        'messages': len(msgs),
        'speakers': {s: len(v) for s, v in sorted(by_speaker.items(), key=lambda x: -len(x[1]))},
        'over_markers': over,
        'over_per_msg': round(over/n, 3),
        'type_distribution': dict(type_dist.most_common()),
        'review_req': rev_req, 'review_res': rev_res,
        'review_res_per_req': round(rev_res/(rev_req or 1), 3),
        'go_yes_batons': go_yes,
        'closed_loop_ack_rate': round(ack_n/n, 3),     # frac msgs w/ explicit read-back/confirm
        'evidence_block_rate': round(ev_n/n, 3),        # frac msgs w/ Evidence: section
        'receipt_rate': round(receipt_n/n, 3),          # frac msgs w/ SHA or file:line
        'role_divergence_SEI': sei,                     # JS-div of coder vocab (0=identical roles)
        'overhead_TEI': round(boiler_tokens/(total_tokens or 1), 4),  # boilerplate token fraction
        'duplicate_msg_rate': round(dup_msgs/n, 3),       # exact-dup bodies (triple-posting)
        'consec_neardup_rate': round(consec_dup/n, 3),    # same-speaker >0.8 overlap (ack spam)
        # PROXIES (keyword-based; true versions need a controlled multi-arm run + bug ground-truth):
        'review_msgs': review_msgs,
        'reviewer_finding_rate': round(review_findings/(review_msgs or 1), 3),  # proxy: independent-catch
        'escape_admissions': escape_n,                    # proxy: correlated-miss (both-agents-missed)
        # CONVERGENCE QUALITY (over Review Result verdicts). See SCOPE LIMIT above:
        # message-level, a CEILING on premature consensus — not the exchange rate.
        'review_results': rr_total,
        'zero_finding_approve_rate': round(rr_clean/(rr_total or 1), 3),  # rubber-stamp-shaped — HIGH = suspect
        'substantive_review_rate': round(rr_subst/(rr_total or 1), 3),    # ≥1 real finding (a genuine catch)
        'formal_dissent_rate': round(rr_dissent/(rr_total or 1), 3),      # explicit non-approve verdict
        # EXCHANGE-LEVEL (needs Slice: tags; None until the contested-debate spike runs):
        'contested_slices': len(contested_slices),
        'single_exchange_contested_rate': single_exchange_rate,  # contested resolved in 1 turn — HIGH = premature
        'multi_round_contested_rate': multi_round_rate,          # contested with ≥2 turns — the goal
        'avg_tokens_per_msg': round(total_tokens/n, 1),
    }


def main():
    json_out = None
    argv = sys.argv[1:]
    args = []
    i = 0
    while i < len(argv):
        if argv[i] == '--json':
            json_out = argv[i+1]
            i += 2
            continue
        args.append(argv[i])
        i += 1
    results = {}
    for d in args:
        # d is <repo>/docs/agents -> name the repo folder
        p = os.path.abspath(d.rstrip('/'))
        repo = p
        for _ in range(2):  # strip /agents then /docs
            repo = os.path.dirname(repo)
        name = os.path.basename(repo) or d
        results[name] = analyze(find_files(d))
    print(json.dumps(results, indent=2))
    if json_out:
        json.dump(results, open(json_out, 'w'), indent=2)
        print(f"\nwrote {json_out}", file=sys.stderr)


if __name__ == '__main__':
    main()
