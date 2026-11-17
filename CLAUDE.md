# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Backtest module conventions

The historical backtest / validation layer (spec: `docs/BACKTEST_VALIDATION_SPEC.md`) follows these rules:

- **Branch**: all backtest work lands on `feature/backtest-validation`. Never commit to `main`.
- **Isolation**: new backtest logic lives in `modules/backtest/` (harness, scoring, baselines, regimes)
  and new data access in `modules/data_provider/`. Do not entangle it with `app.py` rendering or the
  Streamlit/FastAPI request paths. The live app (`streamlit run app.py`, `uvicorn api.main:app`) and
  `tests/test_api.py` must keep working after every stage.
- **Secrets**: read `MASSIVE_API_KEY` / `FMP_API_KEY` (and any other) from `.env` via
  `assets/config/settings.py` or `api/core/config.py`. Never hardcode, never print key values, never commit `.env`.
- **Interpreter**: always use the repo's own `./.venv/bin/python` and `./.venv/bin/pytest`. Never the
  ambient `python` — it resolves to a different project's venv and lacks this repo's deps (`pydantic_settings`).
- **Tests**: pure logic (density producers, scoring, baselines, regime bucketing) gets unit tests with
  known-answer cases in `tests/`. Add tests alongside the code, run `./.venv/bin/pytest` before each commit.
- **Known pre-existing failure (out of scope for this branch)**: `tests/test_api.py::test_stripe_checkout_flow`
  fails with a `TypeError` (datetime bug in the billing path). It predates this work and is sensitive —
  do NOT fix it here. Baseline invariant (2026-11-17, feat/engine-corrected): **207 passed, 34 skipped, this 1 Stripe failure**.
  The 34 skips are tests that need raw snapshots in `data/raw/` (gitignored); `tests/conftest.py` skips them one by one
  when the snapshot is missing and `pytest.ini` limits collection to `tests/`. No regression from that.
- **Reuse, don't rebuild**: the density core (`modules/utils.py::compute_rnd_from_clean_calls` /
  `compute_rnd_from_calls`) is pure and as-of-safe — feed a historical chain + past dates for a past RND.
  Ground-truth `S_T` comes from `modules/data_provider/fmp.py::fetch_quote_history`.
