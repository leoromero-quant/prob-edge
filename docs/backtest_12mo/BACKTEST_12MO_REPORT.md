# Prob-Edge RND Backtest — Reviewer Package (12-month, six-way)

**Headline (precise):** *A proper density extraction beats the broker's ATM expected move on CRPS, out of
sample, consistently across every name and regime; the vanilla Prob-Edge cone did not. The one residual is
a small 95%-tail gap from wing modeling — disclosed, and not a measure effect.*

Out-of-sample backtest: **12 monthly 2025 expiries × SPY/QQQ/AAPL × 2 DTE = 72 triples, 432 scored rows**,
six methods, one scorer, one frozen chain cache. Companion notebook: `notebooks/backtest_report.ipynb`
(PIT plots + tables, re-derives everything from the committed scores). Supersedes `docs/backtest_mvp/`.

### The methods

| method | what it is | role |
| --- | --- | --- |
| `atm_iv_normal` | broker expected move `S·σ_ATM·√T`, ±1σ/±1.96σ | **headline baseline** (the broker screen) |
| `atm_iv_lognormal` | same move, lognormal (RN drift) | supporting comparator |
| `delta_pop` | CDF(K)=1−\|call Δ\| (tastytrade POP proxy) | supporting comparator |
| `bl` | vanilla Breeden-Litzenberger cone | current Prob-Edge product |
| `corrected` | RN extraction, **SVI no-arb wings** | candidate — best CRPS |
| `corrected_quad` | RN extraction, flat (quadratic) wings | candidate — best body calibration |

**Two corrected variants are presented on purpose — no single winner is forced.** Both are cleaner
risk-neutral *extractions* (measure decision (a)); the choice between them is a real trade-off:

- **`corrected` (SVI):** best CRPS (10.14), theoretically correct no-arb wings; runs slightly tight
  (cov68 0.62).
- **`corrected_quad` (flat-wing):** best body calibration (cov68 0.68 on the nose), CRPS still beats the
  broker (10.49), Winkler95 marginally better (90.5 vs 91.5).

**Both beat the broker on CRPS in every ticker and every regime, and both beat the vanilla cone on every
metric.** Neither closes the Winkler95 tail gap — that residual is real and stays visible below.

---

## Results (n=72 per method)

#### Overall (nominal cov 0.68 / 0.95)

| method | cov68 | cov95 | Winkler68 | Winkler95 | **CRPS** | PIT | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 0.71 | 0.96 | 58.3 | **87.9** | 10.83 | 0.59 | 0 |
| atm_iv_lognormal | 0.75 | 0.97 | 58.0 | 91.4 | 10.85 | 0.59 | 0 |
| delta_pop | 0.78 | 0.97 | 64.5 | 101.7 | 11.33 | 0.55 | 22 |
| bl (vanilla) | 0.90 | 0.99 | 89.1 | 134.7 | 14.39 | 0.55 | 27 |
| **corrected (SVI)** | 0.62 | 0.93 | **56.7** | 91.5 | **10.14** | 0.56 | 0 |
| **corrected_quad** | 0.68 | 0.99 | 57.1 | 90.5 | 10.49 | 0.57 | 0 |

Both corrected variants win CRPS and Winkler68; the broker keeps the best Winkler95 (tails); `bl` is worst
on every metric and tail-clips 27/72.

#### CRPS by regime (per-ticker realized-vol terciles, n=24 each) — the durable claim

| regime | atm_iv_normal | corrected (SVI) | corrected_quad | bl |
| --- | --- | --- | --- | --- |
| low | 8.90 | **8.05** | 8.33 | 11.46 |
| mid | 9.73 | **9.42** | 9.62 | 14.42 |
| high | 13.88 | **12.93** | 13.53 | 17.29 |

**Both corrected variants beat the broker on CRPS in all three regimes** (SVI best in each). By ticker the
same holds: CRPS corrected < broker for SPY, QQQ, AAPL — all six ticker×regime CRPS cuts favor corrected.

#### Winkler95 by regime — where the residual lives

| regime | atm_iv_normal | corrected (SVI) | corrected_quad | bl |
| --- | --- | --- | --- | --- |
| low | 72.8 | **69.2** | 76.1 | 102.6 |
| mid | 97.4 | 98.3 | **92.7** | 127.0 |
| high | **93.4** | 107.1 | 102.5 | 174.4 |

`corrected` wins Winkler95 in **low** vol; the broker wins in **high** vol, where the corrected wings
under-cover at 95% (cov95 0.92 SVI). This localized high-vol tail is the entire residual.

#### PIT histogram (counts per decile; flat = calibrated)

| method | 0.0 | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 3 | 9 | 0 | 4 | 6 | 10 | 10 | 12 | 11 | 7 |
| atm_iv_lognormal | 4 | 7 | 1 | 4 | 6 | 9 | 11 | 12 | 11 | 7 |
| delta_pop | 5 | 2 | 7 | 6 | 10 | 10 | 10 | 9 | 8 | 5 |
| bl | 0 | 4 | 4 | 8 | 17 | 9 | 14 | 10 | 3 | 3 |
| corrected (SVI) | 8 | 4 | 4 | 4 | 6 | 9 | 9 | 10 | 7 | 11 |
| corrected_quad | 3 | 9 | 2 | 4 | 5 | 12 | 9 | 10 | 12 | 6 |

`bl` is centre-piled (over-dispersed → too wide). `corrected (SVI)` is mildly U-shaped (edges 8/11 →
slightly under-dispersed, matching cov95 0.93). `corrected_quad` and the broker are closest to flat.

---

## Reading the result

1. **A proper RN extraction beats the broker on CRPS, out of sample, in every name and regime** — true for
   both corrected variants. The **vanilla `bl` cone does not** (CRPS 14.39, worst on everything), so the
   win is about *extraction quality*, not about having an option-implied density per se.
2. **The residual is a small, localized 95%-tail gap** (broker Winkler95 87.9 vs corrected ~90–92, driven
   by high-vol 95% under-coverage). SVI's no-arb wings *narrowed* it (winning Winkler95 in low vol / AAPL)
   but did not close it. **We do not claim "beats on everything."**
3. **The residual is a wing-modeling effect, not a measure effect** — hence a physical-measure (VRP)
   treatment is not indicated (it would damage the near-nominal body to chase the tail). Building stopped
   at SVI by design.

## Health & caveats (honesty first)

- **Coverage / calibration:** SVI runs slightly tight (cov68 0.62, cov95 0.93); flat-wing is better in the
  body (cov68 0.68). Both shipped; the trade-off is the reviewer's to weigh, not ours to hide.
- **`bl` tail-clips 27/72 and `delta_pop` 22/72** (cone reaches the fetched-window edge) — their scores
  are, if anything, understated; corrected and the ATM baselines never clip.
- **IV inversion ≥69% per chain**; far-OTM no-trade strikes are flagged `NaN`, never guessed (159 total).
- **0 CRPS-truncated, 0 dropped, 0 producer errors** across all 432 rows (common padded grid, tails to 0/1).
- **Sample sizes:** n=72 aggregate is robust; per-regime and per-ticker cells are n=24 — meaningful but
  directional. The CRPS ordering (corrected > broker > vanilla) is consistent across **all** cuts.
- **Guardrails:** every density is fit only to construction-time option data; **no parameter is fit to
  realized `S_T`**; scoring is strictly out of sample.
- **Not pursued (per plan):** SSVI (globally butterfly-arb-free) or a mild high-vol wing widening could
  target the residual 95% under-coverage. Building stops at SVI.
- **Test status:** all backtest unit tests pass; the only failing tests are a live-dxFeed market-data
  timeout and a pre-existing Stripe billing datetime bug — neither in this code path.

## Reproducibility

The **72 option chains are frozen** under `docs/backtest_12mo/chains/` (the auditable dataset). Re-runs
read them from disk — **no Polygon calls, byte-identical results.** The notebook re-derives every table and
plot from `docs/backtest_12mo/backtest_scores.parquet`.

```bash
cd /home/leo/projects/Risk-Neutral-Density-Probabilities
./.venv/bin/python -m modules.backtest.run_report \
  --tickers SPY QQQ AAPL \
  --expiries 2025-01-17 2025-02-21 2025-03-21 2025-04-17 2025-05-16 2025-06-20 \
             2025-07-18 2025-08-15 2025-09-19 2025-10-17 2025-11-21 2025-12-19 \
  --dte 30 7 --strike-step 5 --workers 1 \
  --methods atm_iv_normal atm_iv_lognormal delta_pop bl corrected corrected_quad \
  --cache-dir docs/backtest_12mo/chains
# then: jupyter notebook notebooks/backtest_report.ipynb
```

Raw per-triple scores: [`backtest_scores.csv`](backtest_scores.csv) (432 rows = 72 triples × 6 methods).
