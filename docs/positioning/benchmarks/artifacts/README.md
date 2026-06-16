# Reproducible metric artifacts

The prose benchmark docs in the parent directory cite collaboration metrics
(zero-finding-approve rate, substantive-review rate, dissent rate, role
divergence / SEI, convergence quality, …). This folder makes the *pipeline*
behind those numbers reproducible from committed data, so a reader can verify
the tool rather than trust the prose (an external audit's fair ask).

## What's here

- **`sample-metrics.json`** — the metrics for a small committed comms thread
  (`tests/fixtures/comms-sample/`), produced by `scripts/comms-metrics.py`. It
  is the deterministic output of the tool on shipped input: regenerate it and
  you get the same file. `tests/test_benchmark_artifact.py` enforces that — if
  the metric definitions or the fixture change, the artifact must be
  regenerated, or the test fails.

## Reproduce it

```bash
python3 scripts/comms-metrics.py tests/fixtures/comms-sample/docs/agents \
    --json docs/positioning/benchmarks/artifacts/sample-metrics.json
```

Run `scripts/comms-metrics.py <your-project>/docs/agents` against any real bed's
comms directory to get the same schema for your own runs (add `--json out.json`
to write a machine-readable artifact).

## Schema (selected keys)

| key | meaning |
|-----|---------|
| `review_results` | count of `Type: Review Result` messages |
| `zero_finding_approve_rate` | fraction of reviews that approved with no finding — **high is suspect** (rubber-stamp-shaped) |
| `substantive_review_rate` | fraction with ≥1 real finding (a genuine catch) |
| `formal_dissent_rate` | fraction with an explicit non-approve verdict |
| `contested_slices` | slices whose reviews raised a finding or dissent (needs `Slice:` tags) |
| `single_exchange_contested_rate` | contested slices resolved in one turn — **high = premature consensus** |
| `multi_round_contested_rate` | contested slices that took ≥2 turns — the goal |
| `role_divergence_SEI` | Jensen-Shannon divergence of the two coders' vocab (0 = identical roles) |
| `reviewer_finding_rate` | proxy for independent-catch rate |
| `escape_admissions` | proxy for correlated-miss (both agents missed it) |

The full key set is the return value of `analyze()` in `scripts/comms-metrics.py`.

## Honest scope

This worked example proves the pipeline; it is **not** a headline result. The
numbers in the prose benchmark docs come from real runs on private production
corpora (cc-aic / portfolio / okami) that are not shippable in a public repo —
so those specific figures are reproducible *by the operator with the corpus*,
not from this repository. The cost figures in the README (~EUR build cost, the
order-of-magnitude multiple) are from a single private build and are **not**
reproducible artifacts at all — they are labelled as a one-project signal, not
a benchmark. Keep that line crisp: the *metric tooling* is reproducible here;
the *private-corpus numbers* are reproducible only where the corpus lives.
