# Prob-Edge RND Backtest — Three-Way Report

**Question:** does the risk-neutral-density (RND) cone beat the broker's expected move, out of
sample, and can a cleaner extraction fix the vanilla cone? **Headline:**

- The **vanilla** Breeden-Litzenberger cone (`bl`) **loses** to the broker ATM-IV expected move on
  every proper metric (CRPS 17.6 vs 14.7), over-covering badly (cov68 0.87 vs 0.68 nominal).
- A **corrected** RN extraction (`corrected`) — same risk-neutral measure, just a cleaner method —
  **decisively beats the vanilla cone** (CRPS 14.75 vs 17.60, Winkler95 96 vs 161, tail-clips 0 vs 10)
  and **ties / edges the broker** (CRPS 14.75 vs 14.71; Winkler95 **96.3 vs 104.6**).

The important, honest lesson: **much of the vanilla cone's "too wide" was extraction noise, not the
variance risk premium.** The clean RN density is far tighter — competitive with the broker screen
*without any measure change* — though it now slightly **under**-covers at 68% (0.50), so it is not
nominally calibrated either.

> **Measure (decision (a), risk-neutral):** all three methods carry implied/RN-side dispersion and are
> scored against realized `S_T` under P. `corrected` is a **better RN extraction**, explicitly *not* a
> physical-measure / VRP calibration — no claim is made that it is "correctly calibrated to realized",
> only that it is a cleaner, arb-aware RN density that no longer self-sabotages on noise and truncation.

> **Scope / honesty:** **30-triple first pass** (SPY/QQQ/AAPL × 5 monthly expiries × 2 DTE). The
> aggregate three-way is meaningful; **per-regime cells (9–12) are thin and directional.** A 12-month
> expansion (second cached fill) is required before any ordering is claimed as durable.

---

## What was measured

- **Universe:** SPY, QQQ, AAPL. **Expiries:** 2025-01-17 … 05-16 (monthly). **Construction:** ~30 & ~7
  DTE before each → **30 (ticker, construction, expiry) triples**, 90 scored rows (30 × 3 methods).
- **Three methods, apples-to-apples on one common padded grid per triple:**
  - `atm_iv_normal` — **headline baseline**, the broker expected move `S·σ_ATM·√(T/365.25)` (68 = ±1σ).
  - `bl` — vanilla Breeden-Litzenberger (parity-cleaned calls → price-space 2nd derivative, forward-rescaled).
  - `corrected` — **RN extraction via a smooth arb-aware IV smile** (quadratic in log-moneyness: level +
    skew + curvature) with **flat-wing extrapolation on a ~5σ grid**, prices rebuilt by Black-Scholes then
    Breeden-Litzenberger. Forward-pinned by construction. Measure = Q. Calibrated **only** to option-chain
    implied vols at construction; **no parameter fit to realized `S_T`.**
- **Truth `S_T`:** realized close at expiry; as-of spot at construction. No-realized triples **excluded,
  never imputed** (0 here). **Scoring:** coverage vs 68/95, Winkler, **CRPS (headline)**, PIT — all on a
  generously padded common grid with tails extended to 0/1 (**0 CRPS-truncated**).
- **Regimes:** per-ticker trailing-21d realized-vol terciles measured at construction.

### Explicit, revisitable methodology choices (no silent caps)

| Choice | Value | Note |
| --- | --- | --- |
| Historical chains | Polygon `as_of` contracts + daily aggregates | IV/delta **BS-inverted from the close** (no live greeks on this tier) |
| Price field | `close` | EOD-aligned with the EOD spot; `vw` is a robustness re-run |
| Strike subsampling | `$5` grid | provider is RPM-throttled account-wide; dropped count logged per chain |
| Fetch window | per triple, ~±5σ of expected move | auto-tight SPY / auto-wide AAPL |
| `corrected` smile | quadratic in log-moneyness, flat wings, ~5σ grid | parameter-light, arb-aware, no realized-outcome fit |

---

## Results

#### By method (overall, n=30 triples each; nominal 0.68 / 0.95)

| method | cov68 | cov95 | Winkler68 | Winkler95 | **CRPS** | PIT | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 0.57 | 0.90 | 80.7 | 104.6 | **14.71** | 0.51 | 0 |
| bl | 0.87 | 0.97 | 102.7 | 161.5 | **17.60** | 0.51 | 10 |
| corrected | 0.50 | 0.97 | 80.6 | **96.3** | **14.75** | 0.50 | 0 |

`corrected` is best on Winkler95 and ties the broker on CRPS — a clean RN density, no measure change.
`bl` is worst on every metric and is the only method that tail-clips.

#### By ticker × method

| ticker | method | cov68 | CRPS | Winkler95 |
| --- | --- | --- | --- | --- |
| SPY | atm_iv_normal | 0.50 | 16.89 | 111.6 |
| SPY | bl | 1.00 | 20.61 | 183.4 |
| SPY | corrected | 0.40 | 16.96 | **108.4** |
| QQQ | atm_iv_normal | 0.60 | 18.71 | 145.0 |
| QQQ | bl | 0.80 | 21.36 | 209.1 |
| QQQ | corrected | 0.60 | 18.71 | **115.9** |
| AAPL | atm_iv_normal | 0.60 | 8.54 | **57.1** |
| AAPL | bl | 0.80 | 10.83 | 92.0 |
| AAPL | corrected | 0.50 | 8.58 | 64.6 |

`corrected` beats `bl` in all three names; beats the broker on Winkler95 for SPY & QQQ, ~ties on AAPL.

#### By vol regime × method (per-ticker realized-vol terciles — thin, directional)

| regime | method | n | cov68 | Winkler95 | CRPS |
| --- | --- | --- | --- | --- | --- |
| low | atm_iv_normal | 12 | 0.58 | 128.0 | 13.52 |
| low | bl | 12 | 0.92 | 130.4 | 17.49 |
| low | corrected | 12 | 0.42 | **95.2** | 14.05 |
| mid | atm_iv_normal | 9 | 0.67 | 70.3 | 10.05 |
| mid | bl | 9 | 0.89 | 130.9 | 13.87 |
| mid | corrected | 9 | 0.67 | 75.9 | 10.33 |
| high | atm_iv_normal | 9 | 0.44 | 107.6 | 20.97 |
| high | bl | 9 | 0.78 | 233.5 | 21.49 |
| high | corrected | 9 | 0.44 | 118.2 | **20.10** |

`bl` blows out in high vol (Winkler95 233); `corrected` is the best CRPS in high vol and best Winkler95 in low vol.

#### PIT histogram (counts per decile; flat = calibrated)

| method | 0.0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 3 | 7 | 0 | 1 | 2 | 5 | 2 | 2 | 2 | 6 |
| bl | 0 | 3 | 3 | 3 | 7 | 2 | 6 | 3 | 1 | 2 |
| corrected | 3 | 7 | 0 | 2 | 1 | 6 | 2 | 1 | 2 | 6 |

`bl` is centre-piled (over-dispersed → too wide). `corrected` mirrors the broker's mild edge-heaviness
(slightly under-dispersed → a touch too tight), consistent with its cov68 0.50.

---

## Reading the result

1. **The corrected RN extraction fixes the vanilla cone without changing measure.** Same risk-neutral
   density, better method (smooth arb-aware smile + proper ~5σ tails vs noisy price-space PCHIP +
   ad-hoc rescale): CRPS 17.60 → 14.75, Winkler95 161 → 96, tail-clips 10 → 0.
2. **So the vanilla cone's over-width was mostly extraction noise, not the VRP.** This revises the MVP's
   provisional read: a clean RN density is already **competitive with the broker screen** on CRPS and
   **better on Winkler95**, out of sample, in this window.
3. **But `corrected` is not nominally calibrated** — cov68 0.50 (< 0.68) means it now runs slightly
   *tight* at the 68% band (PIT edge-heavy). Under decision (a) we make no calibration claim; a residual
   dispersion gap remains, which a physical-measure (VRP) treatment — decision (b), deferred — is what
   would target directly.

## Caveats (honesty first)

- **n=30 is a first pass.** Aggregate three-way is credible; per-regime cells (9–12) are directional.
  **No ordering is claimed durable until the 12-month expansion.**
- **`corrected` is a risk-neutral EXTRACTION, not a calibration.** Its competitiveness with the broker is
  a statement about extraction quality + tails, not about being "right under P".
- `bl`'s 10 tail-clips mean its poor scores are, if anything, understated; `corrected` and the broker
  never clip.
- IV inversion ≥79%/chain; far-OTM no-trade strikes flagged NaN, not guessed. **0 CRPS-truncated, 0
  dropped, 0 producer errors** across all 90 rows.
- **Test status:** all backtest unit tests pass. Two live API integration tests currently fail on a
  **dxFeed market-data timeout** (feed availability, unrelated to this code path); one Stripe test fails
  on a pre-existing billing datetime bug. Neither is a regression from the backtest layer.

## Reproduce

```bash
cd /home/leo/projects/Risk-Neutral-Density-Probabilities
# 30 chains frozen under docs/backtest_mvp/chains/ -> re-runs are instant, no Polygon calls
./.venv/bin/python -m modules.backtest.run_report \
  --tickers SPY QQQ AAPL \
  --expiries 2025-01-17 2025-02-21 2025-03-21 2025-04-17 2025-05-16 \
  --dte 30 7 --strike-step 5 --workers 1 \
  --methods atm_iv_normal bl corrected --cache-dir docs/backtest_mvp/chains
```

Raw per-triple scores: [`backtest_scores.csv`](backtest_scores.csv) (90 rows = 30 triples × 3 methods).
