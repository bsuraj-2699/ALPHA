# `eval/scenarios/`

Hand-labeled regression set for the deterministic core of the agent.

Each `*.json` here is a frozen `(context, expected_signal)` pair. CI
loads them all, runs the full orchestrator, and asserts the signal
hasn't drifted. Any change to `rules.json`, the rule evaluator,
override logic, or the decision agent's signal mapping that pushes a
scenario to a wrong class **fails the build**.

The bundled set covers every signal class (`STRONG_BUY`, `BUY`, `HOLD`,
`SELL`, `STRONG_SELL`), every override that has a public-domain example
to lean on (`OVR-O1` fraud, `OVR-O2` guidance withdrawal, `OVR-O3`
dividend cut on declining earnings), and one explicit partial-data
scenario that pins down graceful degradation.

---

## Schema

```jsonc
{
  "name": "Apple FY23 Q1 earnings beat",        // human-readable label
  "description": "Strong YoY EPS, ...",          // what the scenario captures
  "source": "Real event: Apple FY23 Q1 ...",    // where the numbers come from
  "ticker": "AAPL",
  "market": "US",                                // "US" or "IN"
  "expected_signal": "STRONG_BUY",
  "expected_overrides": ["OVR-O1"],              // OPTIONAL, subset-checked
  "expected_min_confidence": 75,                 // OPTIONAL, 0..100
  "expected_max_confidence": 90,                 // OPTIONAL, 0..100
  "notes": "...",
  "context": {
    "market": "US",
    "sector": "technology",
    "eps_yoy_pct": 16.5,
    /* … full RuleEvaluator-shaped dict … */
  }
}
```

### Validation rules

1. **`expected_signal`** is a hard match against `Decision.signal`.
2. **`expected_overrides`** is a *subset* check — the decision's actual
   `overrides_active` must include all expected ones, but may include
   more (we don't pin lower-priority overrides).
3. **`expected_min_confidence` / `expected_max_confidence`** are only
   enforced when present. Use them to lock down "this should be a
   high-conviction BUY" without over-fitting.

---

## Methodology behind the bundled set

| File                                         | Class       | Real event lineage                                                                  |
| -------------------------------------------- | ----------- | ----------------------------------------------------------------------------------- |
| `aapl_2023_q1_earnings_beat.json`            | STRONG_BUY  | AAPL FY23 Q1 earnings (Feb 2 2023) — beat, golden-cross technicals                  |
| `nvda_2023_ai_breakout.json`                 | STRONG_BUY  | NVDA Q1 FY24 (May 24 2023) — datacenter rev surge; +24% next day                    |
| `msft_2023_cloud_steady.json`                | BUY         | MSFT FY23 Q3 (Apr 2023) — Azure +27%, decelerating but solid                        |
| `tech_golden_cross_breakout.json`            | BUY         | Synthetic: textbook golden cross + breakout-on-volume                               |
| `tsla_2024_delivery_miss.json`               | STRONG_SELL | TSLA Q1 2024 deliveries (Apr 2 2024) — first YoY decline                            |
| `peloton_2022_post_pandemic_collapse.json`   | STRONG_SELL | PTON FY22 Q3 (May 10 2022) — demand collapse + cash burn                            |
| `meta_2022_ad_slowdown.json`                 | SELL        | META Q3 2022 (Oct 26 2022) — first revenue decline; -24% next day                   |
| `bear_flag_breakdown.json`                   | SELL        | Synthetic: death cross + momentum collapse on heavy distribution                    |
| `wirecard_fraud_signals.json`                | STRONG_SELL | WDI Jun 2020 — auditor refused to sign; OVR-O1 trips                                |
| `guidance_withdrawn_panic.json`              | SELL        | Pattern from Mar 2020 'pulling guidance' wave; OVR-O2 trips                         |
| `ge_2018_dividend_cut.json`                  | SELL        | GE Nov 2017 / Oct 2018 cuts on falling earnings; OVR-O3 trips                       |
| `kogi_defensive_steady.json`                 | HOLD        | KO-shaped defensive blue-chip in a quiet period                                     |
| `mixed_signals_offsetting.json`              | HOLD        | Bull technicals on a stock with weakening fundamentals — signals cancel             |
| `partial_data_technical_only.json`           | HOLD        | Pre-2015 GDELT gap simulated: only price-derived fields populated                   |
| `macro_recession_cyclical_pressure.json`     | SELL        | Q4 2022-style macro headwind on a cyclical name                                     |

Where a file says "Synthetic" or "Composite" we're emulating a *kind of*
setup rather than a specific public earnings print, because we need
field values precise enough to land in a target signal band without
copying confidential broker data.

---

## Running

```bash
# All scenarios
pytest eval/tests/test_scenarios.py -v

# A specific one
pytest eval/tests/test_scenarios.py -v -k aapl

# Show what the orchestrator actually produced (great for tuning)
pytest eval/tests/test_scenarios.py -v -s -k mixed
```

A failing scenario produces a diagnostic with the scenario name,
expected vs. actual signal, the decision's confidence, and any
overrides that fired:

```
AssertionError:
Scenario: Apple FY23 Q1 earnings beat (aapl_2023_q1_earnings_beat.json)
Description: Strong YoY EPS, expanding margins, golden cross technicals ...
Expected signal: STRONG_BUY
Actual signal: BUY
Reason: signal mismatch: expected STRONG_BUY, got BUY (confidence=72.4, overrides=[])
```

---

## Adding a scenario

You have two paths:

### A. Quick / direct

Drop a new `*.json` matching the schema above into this directory.
`discover_scenarios()` picks it up automatically (any `*.json` whose
name doesn't start with `_` or `.`). The CI test will exercise it on
the next run.

### B. Through the factory (recommended for variants of existing setups)

`scenarios/_factory.py` keeps a single well-tested baseline context dict
and expresses each bundled scenario as `baseline + a few overrides`.
That way:

- field names are typed once (typo'd field names silently skip rules),
- the diff for a new scenario is minimal and reviewable,
- regenerating is one command.

To add via the factory:

1. Append an entry to `SCENARIOS` in `_factory.py`:
   ```python
   {
       "filename": "ticker_event.json",
       "name": "Human-readable name",
       "description": "What this captures",
       "source": "Real event lineage or 'Synthetic'",
       "ticker": "TICK", "market": "US",
       "expected_signal": "BUY",
       "deltas": [_STRONG_BULL, {"current_price": 123.0, ...}],
   }
   ```
2. Run `python -m eval.scenarios._factory` to regenerate the JSON.
3. Commit both the factory change and the regenerated JSON.

---

## Roadmap to 50-100 scenarios

The bundled 15 are the *minimum viable regression set* — broad coverage
across signal classes and override paths. Scaling to 50-100 means:

- **More earnings beats / misses** with sector variation (financials,
  energy, healthcare, REITs).
- **More technical setups** beyond golden-cross / death-cross
  (consolidations, false breakouts, gap-and-go).
- **More macro regimes** (high-rate vs. low-rate, growth vs. value
  rotations).
- **IN-market scenarios** beyond the implicit baseline — RELIANCE post-
  Jio, INFY guidance pulls, DLF debt overhang, etc.
- **Override edge cases** — `OVR-O4` (stop-loss-triggered pause) and
  `OVR-O5` (concentration cap) need portfolio-state context, which
  requires extending the runner to thread state into the context dict.

The factory pattern makes mass-adding cheap; each new scenario is a
~10-line entry in `_factory.py`.
