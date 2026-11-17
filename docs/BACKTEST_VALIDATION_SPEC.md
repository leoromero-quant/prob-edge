# Prob-Edge Backtest & Validation Layer — Spec (LossDog bar)

**Branch for this work:** `feature/backtest-validation`.
**Goal:** a historical backtest that meets an external reviewer's bar: outcome-first, coverage plus proper scoring, "better, not just different," by vol regime, three-way (ATM-IV baseline vs vanilla Breeden-Litzenberger cone vs a corrected density).

---

## Reuse (do not rebuild)

- Density core, pure and as-of-safe: `modules/utils.py::compute_rnd_from_clean_calls` and `compute_rnd_from_calls`, signature `(chain_or_clean_calls, spot, valuation_date, expiry_date, r_annual, q_annual, ...) -> (K_grid, pdf_K)`. No network, no "today." Feed a historical chain + past dates → correct past RND, unchanged.
- Put-call parity cleaning: `modules/utils.py::build_clean_calls_from_chain`.
- Cone quantiles: `modules/plots.py::compute_quantile_bands` (CDF via cumsum; 2.5/16/50/84/97.5). Duplicated in `app.py:205` and `app.py:135`.
- Realized truth + as-of spot: `modules/data_provider/fmp.py::fetch_quote_history` (daily EOD, arbitrary past dates) = ground-truth `S_T`.
- Baseline inputs already fetched but discarded: `fetch_options_snapshot` returns per-strike `iv` and `delta`.
- Provider abstraction: `modules/data_provider/`; `massive.py` (Polygon) is the template for a historical fetcher.

## The one blocker: historical option chains

Live snapshot only; nothing persisted. Solve both ways:
1. **Backfill now:** `modules/data_provider/historical_chain.py` pulling Polygon historical options aggregates (`MASSIVE_API_KEY` already held; mirror `massive.py`). Confirm the Polygon tier/endpoint actually returns historical chains for SPY/QQQ/AAPL before building.
2. **Record forward:** `modules/data_provider/chain_store.py` writing each live snapshot to parquet (cron), building your own auditable store.

Normalize both to: `strike, option_type, price (or bid/ask), iv, delta`.

---

## Phases

**A. Enabling refactors.** One shared `cdf_quantiles(K_grid, pdf)` helper replacing the three duplicates (`plots.py:7`, `app.py:205`, `app.py:135`). A density-producer registry `{"bl": compute_rnd_from_clean_calls, "corrected": ...}` selected by a `method` arg at `app.py:610-624` and `api/routes/options.py::_prepare_rnd_data:85`. Fix the year-fraction inconsistency (`utils.py:265` uses 365.0 vs 452/548 use 365.25).

**B. Historical chain access.** `historical_chain.py` (Polygon aggregates), optional `chain_store.py` (parquet). Contract `(ticker, expiry, as_of_date) -> chain_df`.

**C. Backtest harness** (`modules/backtest/driver.py`). Iterate `(ticker, construction_date, expiry)`. Default construction ~30 DTE and ~7 DTE before each expiry, 12-24 months of expiries, SPY/QQQ/AAPL. Per triple per method: load chain → producer → `(K_grid, pdf)` → store cone quantiles + full pdf. Join `S_T` from `fetch_quote_history`.

**D. Scoring** (`modules/backtest/scoring.py`), exactly:
- Coverage: `1{q16≤S_T≤q84}`, `1{q2.5≤S_T≤q97.5}`; empirical vs nominal 68/95.
- Winkler / interval score for central (1−α) interval [L,U]: `(U−L) + (2/α)(L−S_T)·1{S_T<L} + (2/α)(S_T−U)·1{S_T>U}`. Lower better. 68 → α=0.32, 95 → α=0.05.
- CRPS from the discrete cone: `∫ (F(x) − 1{x≥S_T})² dx`, F the cone CDF on K_grid. Lower better. Headline metric.
- PIT: `F(S_T)` per obs; uniform histogram = calibrated. Diagnostic.

**E. Baselines** (`modules/backtest/baselines.py`): ATM-IV expected move (`S·σ_ATM·√(T/365)`, 68=±1σ, 95=±1.96σ, offer lognormal variant) and delta-POP (`P(S_T>K)≈|delta|` → implied CDF/quantiles). Score identically.

**F. Vol regime** (`modules/backtest/regimes.py`): bucket by trailing 21d realized vol terciles (or VIX) measured at construction. Report every metric within regime.

**G. Corrected density** (`modules/rnd_corrected.py`), same contract, drop-in producer. Where the variance-swap critique + rough-Bergomi proxy land.
- CRITICAL measure consistency: the vanilla path pins `E_Q[S_T]` to the theoretical forward (`utils.py:571-590`), i.e. risk-neutral. If the corrected density is physical-measure, score both consistently or coverage is biased. Decide and document: (a) stay risk-neutral, corrected = a better RN extraction; or (b) physical measure with an explicit variance-risk-premium adjustment, compared vs realized under P. A vanilla RN cone runs wide vs realized (VRP) and will not cleanly beat ATM-IV, which is the same measure; the VRP-corrected density is what should win on CRPS/coverage. If it does not, report it straight.

**H. Report + outputs.** Reproducible notebook + one-page methodology; tables coverage×method×regime, Winkler×method, CRPS×method (headline), PIT histograms; three-way ATM-IV vs BL vs corrected.

---

## Minimum viable ship

A + B(1) + C + D + E, run two-way (ATM-IV vs vanilla BL), scored by coverage/Winkler/CRPS, by regime, on SPY/QQQ/AAPL. Answers "does the cone beat the broker's expected move, measured honestly." Do not gate the first ship on G.

## Guardrails

- Secrets via `.env` only (tastytrade OAuth, `FMP_API_KEY`, `MASSIVE_API_KEY`); never commit. Centralized in `assets/config/settings.py` and `api/core/config.py`.
- Market data only; no account data, no trading. Separate from the tastytrade account TWR audit (different repo, different proof).
- The live app must keep working: `streamlit run app.py` and `uvicorn api.main:app` after every stage.
- Honesty: if the corrected density does not beat ATM-IV, publish that.

## Open (do not block)

Universe/DTE unconfirmed by LossDog. Default POC to SPY/QQQ/AAPL at ~30 DTE and ~7 DTE, state the assumption; full report adapts later.
