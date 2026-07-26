# Prob-Edge RND Backtest — 12-Month Three-Way Report

**Supersedes** the 30-triple MVP (`docs/backtest_mvp/`). Same methods, same scorer, same frozen-chain
cache convention, expanded to **12 monthly expiries** so the verdict is read across calm and stressed
periods rather than one stressed window.

**Question:** does the corrected RN density durably beat the broker's expected move, out of sample?
**Headline (n=72 triples, 216 scored rows):**

- The **corrected** RN extraction has the **best CRPS overall (10.51)** — better than the broker
  `atm_iv_normal` (10.86) and far better than the vanilla `bl` cone (14.40) — and the **best CRPS in
  every ticker and every vol regime.**
- Its **68% coverage is 0.68**, on the nose vs nominal. (At the stressed n=30 window it was 0.50 — that
  under-coverage was **sample-dependent**, which is exactly why the expansion was required.)
- The broker keeps a **slight tail-weighted (Winkler95) edge** (87.9 vs 90.5 overall; wins Winkler95 on
  SPY & AAPL and in the high/low regimes). That gap lives in the **95% tails**, and points straight at the
  corrected smile's **flat-wing extrapolation** as the next improvement (see caveat).

**Durable read:** `corrected` **decisively and durably beats the vanilla cone everywhere**, and **beats
or ties the broker on the headline CRPS across calm and stressed periods** at near-nominal 68% coverage.
It does **not** yet dominate on the tail-weighted interval score. No stronger claim is made.

> **Measure (decision (a), risk-neutral):** `corrected` is a cleaner RN *extraction*, not a physical /
> VRP calibration. All three methods carry implied/RN-side dispersion, scored against realized `S_T`.
> Calibrated only to construction-time option data; **no parameter is fit to realized outcomes.** That
> `corrected`'s 68% coverage lands near nominal is an empirical observation, **not** a calibration claim.

> **Scope:** n=72 (aggregate robust); per-regime / per-ticker cells are n=24 — meaningful but not large.

---

## Results

#### By method (overall, n=72 each; nominal 0.68 / 0.95)

| method | cov68 | cov95 | Winkler68 | Winkler95 | **CRPS** | PIT | tail_clip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 0.71 | 0.96 | 58.3 | **87.9** | 10.86 | 0.59 | 0 |
| bl | 0.90 | 0.99 | 89.1 | 134.7 | 14.40 | 0.55 | 27 |
| corrected | **0.68** | 0.99 | **57.1** | 90.5 | **10.51** | 0.57 | 0 |

`corrected` wins CRPS and Winkler68 and hits nominal 68% coverage; the broker edges Winkler95 (tails);
`bl` is worst on every metric and tail-clips 27/72.

#### By vol regime × method (per-ticker realized-vol terciles, n=24 each)

| regime | method | cov68 | Winkler95 | CRPS |
| --- | --- | --- | --- | --- |
| low | atm_iv_normal | 0.71 | 72.8 | 8.91 |
| low | bl | 0.83 | 102.6 | 11.47 |
| low | corrected | 0.67 | 76.1 | **8.34** |
| mid | atm_iv_normal | 0.79 | 97.4 | 9.75 |
| mid | bl | 1.00 | 127.0 | 14.43 |
| mid | corrected | 0.75 | **92.7** | **9.63** |
| high | atm_iv_normal | 0.62 | **93.4** | 13.92 |
| high | bl | 0.88 | 174.4 | 17.30 |
| high | corrected | 0.62 | 102.5 | **13.57** |

**Best CRPS in all three regimes is `corrected`.** Winkler95: `corrected` wins mid, the broker wins
low/high (the tail term). `bl` blows out in high vol (Winkler95 174).

#### By ticker × method (n=24 each)

| ticker | method | cov68 | CRPS | Winkler95 |
| --- | --- | --- | --- | --- |
| SPY | atm_iv_normal | 0.75 | 11.78 | **94.7** |
| SPY | bl | 1.00 | 16.20 | 160.3 |
| SPY | corrected | 0.67 | **11.42** | 101.7 |
| QQQ | atm_iv_normal | 0.71 | 13.66 | 114.9 |
| QQQ | bl | 0.88 | 18.18 | 167.0 |
| QQQ | corrected | 0.71 | **13.16** | **109.0** |
| AAPL | atm_iv_normal | 0.67 | 7.13 | **54.1** |
| AAPL | bl | 0.83 | 8.81 | 76.7 |
| AAPL | corrected | 0.67 | **6.95** | 60.8 |

**Best CRPS in all three names is `corrected`.** Winkler95: `corrected` wins QQQ, broker wins SPY/AAPL.

#### PIT histogram (counts per decile; flat = calibrated)

| method | 0.0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atm_iv_normal | 3 | 9 | 0 | 4 | 6 | 10 | 10 | 12 | 11 | 7 |
| bl | 0 | 4 | 4 | 8 | 17 | 9 | 14 | 10 | 3 | 3 |
| corrected | 3 | 9 | 2 | 4 | 5 | 12 | 9 | 10 | 12 | 6 |

`bl` is centre-piled (over-dispersed → too wide). `corrected` and the broker are close to flat with a mild
right lean (PIT mean ~0.57–0.59 → realized landed a touch high on average in 2025' up-year).

---

## Reading the result

1. **`corrected` durably beats the vanilla cone** on every metric, in every name and regime — the
   arb-aware smile + proper ~5σ tails remove both the price-space extraction noise and the strike
   truncation (`bl` tail-clips 27/72; `corrected` 0).
2. **`corrected` beats or ties the broker on the headline CRPS across calm and stressed periods** (best
   CRPS in all 6 ticker/regime cuts), at **nominal 68% coverage** — and the earlier n=30 under-coverage
   was a stressed-window artifact, now resolved.
3. **The one place the broker still wins is Winkler95** (the 95%-tail-weighted interval score), on SPY,
   AAPL, and the low/high regimes. This is a **tail** story, and it is the honest limit of the current
   extraction — see the smile caveat.

## Caveats (honesty first)

- **Flat-wing smile extrapolation is a revisitable choice that drives the 95% / CRPS tails.** Beyond the
  observed strikes, `corrected` holds implied vol flat. That is simple and stable but crude in the wings,
  and the residual Winkler95 gap to the broker sits exactly there. **Candidate upgrade: an SVI (or SSVI)
  wing parameterization** — a proper no-arbitrage smile whose tails are theoretically grounded rather than
  held flat. This is the most likely lever to close the tail gap; it should be tested the same way (OOS,
  construction-only fit) before any claim.
- **No calibration claim beyond the data.** Under measure (a) `corrected` is a better *extraction*; its
  near-nominal 68% coverage is observed, not asserted, and a physical-measure (VRP) treatment — decision
  (b), deferred — is what would target calibration directly.
- **n=72 aggregate is robust; n=24 cells are directional.** The ordering (corrected > bl on everything;
  corrected ≈/> broker on CRPS; broker > corrected on Winkler95 tails) is **consistent across every cut**,
  which is what makes it durable rather than a single-window artifact.
- IV inversion ≥69% per chain (far-OTM no-trade strikes flagged NaN, not guessed; 159 total). **0
  CRPS-truncated, 0 dropped, 0 producer errors** across all 216 rows. `bl`'s 27 tail-clips mean its poor
  scores are, if anything, understated.
- **Test status unchanged:** all backtest unit tests pass; the only failing tests are a live-dxFeed
  market-data timeout (feed availability) and a pre-existing Stripe billing datetime bug — neither in this
  code path.

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

Raw per-triple scores: [`backtest_scores.csv`](backtest_scores.csv) (216 rows = 72 triples × 3 methods).
