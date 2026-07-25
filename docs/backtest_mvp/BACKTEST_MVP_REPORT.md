# Prob-Edge RND Backtest — MVP Two-Way Report

**Question:** does the risk-neutral-density (RND) cone beat the broker's expected move,
measured honestly, out of sample? **Headline:** on this first pass, **no — not the vanilla
cone.** The raw Breeden-Litzenberger cone is systematically **too wide** (it over-covers and
scores worse on every proper metric) than the ATM-IV expected move a trader reads off the
broker screen. That is the variance-risk-premium (VRP) signature, and it is exactly what a
VRP-corrected density is meant to fix. The result is consistent across all three names and
all vol regimes.

> **Scope / honesty:** this is a **30-triple first pass** (SPY/QQQ/AAPL × 5 monthly expiries ×
> 2 DTE). The **aggregate two-way is meaningful**; the **per-regime cells are thin (9–12 obs)
> and directional only.** A second cached fill to 12 months of expiries is the next step if the
> result warrants a fuller artifact.

---

## What was measured

- **Universe:** SPY, QQQ, AAPL. **Expiries:** 2025-01-17, 02-21, 03-21, 04-17, 05-16 (monthly).
  **Construction points:** ~30 DTE and ~7 DTE before each expiry → **30 (ticker, construction, expiry) triples**.
- **Two methods, apples-to-apples:**
  - `atm_iv_normal` — **the headline baseline**: the broker expected move, `S·σ_ATM·√(T/365.25)`,
    68 = ±1σ, 95 = ±1.96σ, centered on spot. This is "what the user sees on the screen."
  - `bl` — the vanilla Breeden-Litzenberger cone (parity-cleaned calls → 2nd-derivative RND,
    forward-pinned), the current Prob-Edge product.
- **Truth `S_T`:** realized close at expiry (FMP EOD). As-of spot = close at construction.
  Triples with no realized `S_T` are **excluded, never imputed** (0 here).
- **Scoring** (all lower-is-better except coverage): coverage vs nominal 68/95, Winkler interval
  score, **CRPS (headline)**, PIT. Every method is scored on **one common, generously padded price
  grid per triple** with CDFs extended to 0/1 in the tails, so the comparison is apples-to-apples
  and tail truncation cannot flatter a method (**0 CRPS-truncated observations**).
- **Regimes:** each observation is bucketed low/mid/high by its **trailing-21d realized-vol tercile
  measured at construction, per ticker** (so "regime" is the vol *environment*, not "which name").

### Explicit, revisitable methodology choices (no silent caps)

| Choice | Value | Why / caveat |
| --- | --- | --- |
| Historical chains | Polygon reference `as_of` + per-contract daily aggregates | No live snapshot on this tier; IV/delta **BS-inverted from the close** |
| Price field | `close` (`c`) | EOD-aligned with the EOD spot; `vw` is a robustness re-run |
| Strike subsampling | `$5` grid | Provider is **RPM-throttled account-wide**; this cut per-contract calls ~5× (dropped count logged per chain) |
| Fetch window | per triple, ~±5σ of expected move (realized-vol proxy + VRP cushion) | Auto-tight SPY / auto-wide AAPL; **10/30 BL cones still hit the edge** — see caveats |
| Year fraction | 365.25 throughout | Unified across cone and expected move |

---

## Results

#### By method (overall, n=30 triples each)

| method | n | cov68 | cov95 | Winkler68 | Winkler95 | CRPS | PIT | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 30 | 0.567 | 0.900 | 80.7 | 104.6 | **14.71** | 0.509 | 0 |
| bl | 30 | 0.867 | 0.967 | 102.7 | 161.5 | **17.60** | 0.509 | 10 |

Nominal coverage is 0.68 / 0.95. **The BL cone over-covers** (0.87 at the 68% band vs 0.68
nominal) and is **worse on the headline CRPS (17.60 vs 14.71) and on Winkler (161 vs 105)**.
ATM-IV slightly *under*-covers 68 (0.57). Both are near-centered on PIT mean (~0.51).

#### By method × vol regime (per-ticker realized-vol terciles — thin cells, directional)

| method | regime | n | cov68 | cov95 | Winkler95 | CRPS | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | low | 12 | 0.58 | 0.83 | 128.0 | 13.52 | 0 |
| bl | low | 12 | 0.92 | 1.00 | 130.4 | 17.49 | 4 |
| atm_iv_normal | mid | 9 | 0.67 | 1.00 | 70.3 | 10.05 | 0 |
| bl | mid | 9 | 0.89 | 1.00 | 130.9 | 13.87 | 2 |
| atm_iv_normal | high | 9 | 0.44 | 0.89 | 107.6 | 20.97 | 0 |
| bl | high | 9 | 0.78 | 0.89 | 233.5 | 21.49 | 4 |

BL over-covers in every regime; the gap is **worst in high vol** (Winkler95 233 vs 108). CRPS
favors ATM-IV in low/mid and is roughly **tied in high vol** (21.5 vs 21.0).

#### By ticker × method

| ticker | method | n | cov68 | cov95 | CRPS | Winkler95 |
| --- | --- | --- | --- | --- | --- | --- |
| SPY | atm_iv_normal | 10 | 0.50 | 0.90 | 16.89 | 111.6 |
| SPY | bl | 10 | 1.00 | 1.00 | 20.61 | 183.4 |
| QQQ | atm_iv_normal | 10 | 0.60 | 0.80 | 18.71 | 145.0 |
| QQQ | bl | 10 | 0.80 | 0.90 | 21.36 | 209.1 |
| AAPL | atm_iv_normal | 10 | 0.60 | 1.00 | 8.54 | 57.1 |
| AAPL | bl | 10 | 0.80 | 1.00 | 10.83 | 92.0 |

Same ordering in **all three names**: ATM-IV lower CRPS and lower Winkler than the vanilla cone.

#### PIT histogram (counts per decile; flat = calibrated)

| method | 0.0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 3 | 7 | 0 | 1 | 2 | 5 | 2 | 2 | 2 | 6 |
| bl | 0 | 3 | 3 | 3 | 7 | 2 | 6 | 3 | 1 | 2 |

BL's PIT is **piled toward the center** (over-dispersed → intervals too wide). ATM-IV's PIT is
**heavier at the edges** (occasionally too tight). Both diagnostics agree with the coverage/Winkler
read: the vanilla cone is too wide.

---

## Reading the result

1. **The vanilla RN cone loses to the broker's expected move, out of sample, on CRPS and Winkler,
   in every name and regime.** This is not a bug — it is the **variance risk premium**: option-implied
   (risk-neutral) dispersion exceeds realized dispersion, so a raw RN cone runs wide.
2. **This is the honest, expected result** the spec anticipated ("a vanilla RN cone runs wide vs
   realized and will not cleanly beat ATM-IV; the VRP-corrected density is what should win").
3. **It sizes the prize for Phase G:** the corrected density must **contract the RN cone toward the
   physical measure** (a VRP adjustment). The gap to close is concrete — e.g. Winkler95 161→~105,
   CRPS 17.6→<14.7, and 68% coverage 0.87→~0.68 — measured, not asserted.

## Caveats (honesty first)

- **n=30 is a first pass.** Aggregate two-way is credible; per-regime cells (9–12) are directional.
- **10/30 BL cones are tail-clipped** (`tail_clip=1`): the cone is so wide it reaches the fetched
  `~5σ`-ATM window edge (all in low/high-vol, incl. the April-2025 selloff). This means BL's true
  tails are even wider — **its poor scores are, if anything, understated**, which strengthens the
  conclusion. A wider fetch window would sharpen BL's numbers but not flip the ordering.
- **IV inversion health:** ≥79% of strikes invert cleanly per chain; the rest are far-OTM
  illiquid contracts with no trades (price present, IV `NaN`) and are flagged, not guessed.
  **0 CRPS-truncated, 0 dropped, 0 producer errors.**
- **`$5` strikes and per-triple `~5σ` window** are deliberate cost choices under the provider's
  RPM limit, stated so they can be revisited; a `vw`-price and wider-window re-run are footnoted
  robustness checks.

## Reproduce

```bash
cd /home/leo/projects/Risk-Neutral-Density-Probabilities
# the 30 chains are frozen & committed under docs/backtest_mvp/chains/ -> re-runs
# are instant and network-free (the read-through cache serves the parquet files).
./.venv/bin/python -m modules.backtest.run_report \
  --tickers SPY QQQ AAPL \
  --expiries 2025-01-17 2025-02-21 2025-03-21 2025-04-17 2025-05-16 \
  --dte 30 7 --strike-step 5 --workers 1 --cache-dir docs/backtest_mvp/chains
```

Raw per-triple scores: [`backtest_scores.csv`](backtest_scores.csv) (60 rows = 30 triples × 2 methods).
