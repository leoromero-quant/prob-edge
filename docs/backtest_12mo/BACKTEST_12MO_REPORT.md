# Prob-Edge RND Backtest — 12-Month Three-Way Report (final, SVI wings)

Final backtest artifact. 12 monthly 2025 expiries × SPY/QQQ/AAPL × 2 DTE = **72 triples, 216 scored
rows**, three-way: broker expected move (`atm_iv_normal`) vs vanilla Breeden-Litzenberger cone (`bl`) vs
the corrected RN density (`corrected`) — now with **SVI no-arbitrage wings** replacing flat-wing
extrapolation. Same scorer, same frozen 72-chain cache. Supersedes `docs/backtest_mvp/`.

## Verdict

- **`corrected` wins the headline CRPS in EVERY ticker and EVERY vol regime** — a clean CRPS sweep
  (overall 10.16 vs broker 10.86 vs vanilla 14.40), and beats the vanilla cone on every metric everywhere.
- **The 95% tail gap narrowed but did not fully close.** SVI's linear no-arb wings sharpened the density:
  in the low-vol regime and on AAPL, `corrected` now also **wins Winkler95**; but overall the broker keeps
  a small Winkler95 edge (87.9 vs 91.5), concentrated in high vol where the sharper wings **slightly
  under-cover at 95%** (cov95 0.92).
- This is the honest **"wins CRPS everywhere, small tail residual"** outcome. It clears the bar. **SVI was
  the last build lever; no further tuning is pursued.**

> **SVI trade-off (stated, not hidden):** SVI is the theoretically correct no-arb wing and wins the
> headline CRPS more decisively, but it runs a touch tight — 68% coverage 0.62 and 95% coverage 0.93,
> both slightly under nominal (its PIT is mildly U-shaped). The earlier flat-wing extraction
> (`smile="quad"`, still available) had better *body* calibration (cov68 0.68 on the nose) but slightly
> worse CRPS and theoretically indefensible flat wings. Default ships SVI (headline + principle); reverting
> is a one-flag change.

> **Measure (decision (a), risk-neutral):** `corrected` is a cleaner RN *extraction*, not a physical/VRP
> calibration. Fit only to construction-time option IV; **no parameter fit to realized `S_T`**; scored OOS.
> No calibration claim beyond the data. The residual is a **wing/extraction** effect, not a measure effect
> — consistent with deprioritizing the physical-measure (b) treatment (a global measure shift would harm
> the near-nominal body to chase the tail).

> **Scope:** n=72 aggregate is robust; per-regime / per-ticker cells are n=24 — meaningful, directional.

---

## Results

#### By method (overall, n=72 each; nominal 0.68 / 0.95)

| method | cov68 | cov95 | Winkler68 | Winkler95 | **CRPS** | PIT | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 0.71 | 0.96 | 58.3 | **87.9** | 10.86 | 0.59 | 0 |
| bl | 0.90 | 0.99 | 89.1 | 134.7 | 14.40 | 0.55 | 27 |
| corrected (SVI) | 0.62 | 0.93 | **56.7** | 91.5 | **10.16** | 0.56 | 0 |

`corrected` wins CRPS and Winkler68; the broker edges Winkler95 (tails); `bl` worst on all, tail-clips 27/72.

#### By vol regime × method (per-ticker realized-vol terciles, n=24 each)

| regime | method | cov68 | cov95 | Winkler95 | CRPS |
| --- | --- | --- | --- | --- | --- |
| low | atm_iv_normal | 0.71 | 0.96 | 72.8 | 8.91 |
| low | bl | 0.83 | 1.00 | 102.6 | 11.47 |
| low | corrected | 0.62 | 0.96 | **69.2** | **8.07** |
| mid | atm_iv_normal | 0.79 | 0.96 | **97.4** | 9.75 |
| mid | bl | 1.00 | 1.00 | 127.0 | 14.43 |
| mid | corrected | 0.67 | 0.92 | 98.3 | **9.46** |
| high | atm_iv_normal | 0.62 | 0.96 | **93.4** | 13.92 |
| high | bl | 0.88 | 0.96 | 174.4 | 17.30 |
| high | corrected | 0.58 | 0.92 | 107.1 | **12.97** |

**Best CRPS in all three regimes is `corrected`.** It also wins Winkler95 in **low** vol; the broker wins
Winkler95 in **high** vol, where `corrected` under-covers at 95% (0.92) — the residual tail.

#### By ticker × method (n=24 each)

| ticker | method | cov68 | CRPS | Winkler95 |
| --- | --- | --- | --- | --- |
| SPY | atm_iv_normal | 0.75 | 11.78 | **94.7** |
| SPY | bl | 1.00 | 16.20 | 160.3 |
| SPY | corrected | 0.62 | **10.84** | 96.8 |
| QQQ | atm_iv_normal | 0.71 | 13.66 | **114.9** |
| QQQ | bl | 0.88 | 18.18 | 167.0 |
| QQQ | corrected | 0.62 | **12.86** | 123.9 |
| AAPL | atm_iv_normal | 0.67 | 7.13 | 54.1 |
| AAPL | bl | 0.83 | 8.81 | 76.7 |
| AAPL | corrected | 0.62 | **6.79** | **53.8** |

**Best CRPS in all three names is `corrected`.** It wins Winkler95 on AAPL; the broker wins SPY/QQQ tails.

#### PIT histogram (counts per decile; flat = calibrated)

| method | 0.0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 3 | 9 | 0 | 4 | 6 | 10 | 10 | 12 | 11 | 7 |
| bl | 0 | 4 | 4 | 8 | 17 | 9 | 14 | 10 | 3 | 3 |
| corrected (SVI) | 8 | 4 | 4 | 4 | 6 | 9 | 9 | 10 | 7 | 11 |

`bl` centre-piled (too wide). `corrected` mildly U-shaped (edges 8 / 11) — slightly **under**-dispersed,
consistent with its 0.93 cov95: the SVI wings run a touch tight.

---

## Reading the result

1. **`corrected` (SVI) is the best density on the headline CRPS, everywhere** — every ticker, every regime,
   out of sample — and dominates the vanilla cone on all metrics (which tail-clips 27/72; `corrected` 0).
2. **SVI narrowed the tail gap but did not close it.** Replacing flat wings with SVI's no-arb linear-
   variance wings sharpened the density: `corrected` now wins Winkler95 in low vol and on AAPL. But in
   high vol the sharper wings **under-cover at 95%** (0.92), so the broker retains a small overall
   Winkler95 edge. The residual is a **wing-calibration** issue, localized to high-vol tails.
3. **The diagnosis holds:** the miscalibration was never a measure problem — it was extraction (vanilla
   noise) then wing shape (flat vs SVI). A physical-measure shift is not indicated and would damage the
   near-nominal body to chase this tail.

## Caveats (honesty first)

- **SVI runs slightly tight** (cov68 0.62, cov95 0.93; U-shaped PIT). Shipped as default because it wins
  the headline CRPS and is the principled no-arb wing; `smile="quad"` (flat-wing) remains available and is
  better calibrated in the body (cov68 0.68). Neither is a clean Winkler95 sweep.
- **No calibration claim beyond the data.** `corrected` is a better RN *extraction*; near-body calibration
  is observed, not asserted.
- **n=72 aggregate robust; n=24 cells directional.** The CRPS ordering is consistent across **all six**
  ticker/regime cuts, which is what makes the CRPS win durable rather than a single-window artifact.
- IV inversion ≥69%/chain (far-OTM no-trade strikes flagged NaN, not guessed; 159 total). **0
  CRPS-truncated, 0 dropped, 0 producer errors** across 216 rows.
- **Test status:** all backtest unit tests pass; the only failing tests are a live-dxFeed market-data
  timeout and a pre-existing Stripe billing datetime bug — neither in this code path.
- **Possible future work (not pursued here):** SSVI (a globally no-butterfly-arb surface) or a mild
  high-vol wing widening could target the residual 95% under-coverage — but per plan, building stops at SVI.

## Reproduce

```bash
cd /home/leo/projects/Risk-Neutral-Density-Probabilities
# 72 chains frozen under docs/backtest_12mo/chains/ -> instant, no Polygon calls
./.venv/bin/python -m modules.backtest.run_report \
  --tickers SPY QQQ AAPL \
  --expiries 2025-01-17 2025-02-21 2025-03-21 2025-04-17 2025-05-16 2025-06-20 \
             2025-07-18 2025-08-15 2025-09-19 2025-10-17 2025-11-21 2025-12-19 \
  --dte 30 7 --strike-step 5 --workers 1 \
  --methods atm_iv_normal bl corrected --cache-dir docs/backtest_12mo/chains
```

`corrected` uses SVI wings by default (`modules/rnd_corrected.py`, `smile="svi"`; `"quad"` = flat-wing).
Raw per-triple scores: [`backtest_scores.csv`](backtest_scores.csv) (216 rows = 72 triples × 3 methods).
