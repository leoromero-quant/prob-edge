# app.py — ProbEdge Unified App
# Tabs: 📊 Densities | 🏢 Company | 💰 Valuation | 📈 Financials | 🌐 Sector
from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from assets.config.settings import settings
from modules.data_provider.tastytrade_options import (
    fetch_available_expiries,
    fetch_options_snapshot,
    get_spot_price as tt_spot_price,
    _get_tt_token,
)
from modules.data_provider.dxfeed_quotes import get_quotes_from_env
from modules.data_provider.fmp import fetch_quote_history as fmp_quote_history
from modules.utils import (
    compute_rnd_from_calls,
    compute_rnd_from_clean_calls,
    build_time_price_density,
    build_clean_calls_from_chain,
)
from modules.plots import plot_main_figure
from modules import rnd_bridge
from modules import rnd_forward as rnd_forward_mod

# Asegurar raíz del proyecto en sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Favicon SVG path. Resolved relative to app.py so it works both locally and
# on Render regardless of CWD. Streamlit accepts SVG paths since v1.30+.
ICON_PATH = ROOT / "assets" / "icon.svg"

st.set_page_config(
    page_title="ProbEdge — Markets Analytics",
    page_icon=str(ICON_PATH) if ICON_PATH.exists() else "📊",
    layout="wide",
)

# Tipografía moderna estilo fintech (Inter para UI, JetBrains Mono para datos).
# Inter = sans geométrica que usan tastytrade/Robinhood/Linear; JetBrains Mono =
# monospace con alternates matemáticos (cero cortado, ligatures), mucho más
# moderna que Consolas pero con el mismo espíritu técnico/financiero.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

    html, body, [class*="css"], .stApp, .stMarkdown, .stTextInput, .stSelectbox,
    .stNumberInput, .stCheckbox, .stRadio, .stButton, .stTextArea,
    .stCaption, .stAlert, h1, h2, h3, h4, h5, h6, p, label, span, div {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-feature-settings: "cv11", "ss01", "ss03";
    }
    code, pre, .stCode, .stDataFrame, .stDataFrameGlideDataEditor,
    .stMetric [data-testid="stMetricValue"], .stMetric [data-testid="stMetricLabel"] {
        font-family: 'JetBrains Mono', 'Consolas', 'SF Mono', monospace !important;
        font-feature-settings: "calt", "zero", "ss01";
    }
    /* Captions de Streamlit con tracking ligero para look financiero */
    .stCaption, [data-testid="stCaptionContainer"] {
        letter-spacing: 0.01em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# === ENTORNO ===
APP_ENV = os.getenv("APP_ENV", "").strip().lower()
IS_DEV = APP_ENV in ("", "dev", "development")

# === API KEYS ===
FMP_API_KEY = os.getenv("FMP_API_KEY", "") or settings.FMP_API_KEY or ""
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929").strip()

# En Stripe Dashboard creas un Payment Link para tu suscripción
STRIPE_PAYMENT_LINK = "https://buy.stripe.com/eVq3cx1Isbd74qLd6BcfK01"


# ─────────────────────────────────────────────
# CACHES — Densidades
# ─────────────────────────────────────────────
@st.cache_data
def cached_quotes(ticker: str, range_code: str, fmp_api_key: str, cache_day: str):
    # cache_day (YYYY-MM-DD) es parte de la clave de caché para forzar un refetch
    # diario. Sin él, un proceso de larga vida (Render) sirve el histórico congelado
    # al día en que se llenó la caché. No se usa dentro de la función.
    range_to_days = {
        "d1": 1, "d5": 5, "m1": 21, "m3": 63, "m6": 126,
        "ytd": 252, "y1": 252, "y2": 504, "y5": 1260, "max": 0,
    }
    days = range_to_days.get(range_code, 252)
    return fmp_quote_history(ticker, fmp_api_key, days=days)


@st.cache_data(ttl=300)
def cached_expiries(ticker: str):
    tt_token = _get_tt_token()
    return fetch_available_expiries(ticker, tt_token)


@st.cache_data(ttl=60)
def cached_options(ticker: str, expiry: str):
    tt_token = _get_tt_token()
    df = fetch_options_snapshot(ticker, expiry, tt_token)
    if df.empty:
        return df
    df = df.rename(columns={
        "contract_type": "option_type",
        "last_price": "last_close",
    })
    bid = df["bid"].astype(float)
    ask = df["ask"].astype(float)
    last = df["last_close"].astype(float) if "last_close" in df.columns else pd.Series(np.nan, index=df.index)
    mid = np.where(
        (bid > 0) & (ask > 0),
        0.5 * (bid + ask),
        np.where(bid > 0, bid, np.where(ask > 0, ask, np.where(last > 0, last, np.nan))),
    )
    df["mid_price"] = mid
    df["price"] = df["mid_price"]
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# PoP table — premium-selling reference (heatmap-styled DataFrame)
# ─────────────────────────────────────────────
def _build_pop_table(K_grid, pdf_K, spot):
    """
    Tabla de referencia para venta de prima. Para una grilla de strikes
    sampleados a niveles fijos del CDF, computa Call PoP y Put PoP risk-neutral.

    Convención:
      - Call PoP = P(S_T ≤ K) = CDF(K)        → prob de que un short call expire OTM.
      - Put  PoP = P(S_T ≥ K) = 1 − CDF(K)    → prob de que un short put expire OTM.

    El CDF se extrae de la RND al vencimiento (ya incorpora todo el skew de IV).
    """
    K_grid = np.asarray(K_grid, dtype=float)
    pdf_K = np.asarray(pdf_K, dtype=float)
    if len(K_grid) < 2:
        return None
    dx_K = float(K_grid[1] - K_grid[0])
    pdf_clean = np.clip(np.nan_to_num(pdf_K), 0, None)
    if pdf_clean.sum() <= 0 or dx_K <= 0:
        return None
    cdf = np.cumsum(pdf_clean) * dx_K
    if cdf[-1] <= 0:
        return None
    cdf = cdf / cdf[-1]

    # Niveles del CDF a los que sampleamos el strike (orden ascendente).
    levels = [0.05, 0.10, 0.16, 0.25, 0.35, 0.50, 0.65, 0.75, 0.84, 0.90, 0.95]
    rows = []
    for lvl in levels:
        idx = int(np.searchsorted(cdf, lvl))
        idx = max(0, min(idx, len(K_grid) - 1))
        K = float(K_grid[idx])
        call_pop = lvl * 100.0
        put_pop = (1.0 - lvl) * 100.0
        pct_spot = (K - float(spot)) / float(spot) * 100.0 if spot else 0.0
        rows.append({
            "Call PoP": round(call_pop, 1),
            "Strike": round(K, 2),
            "Δ spot": round(pct_spot, 1),
            "Put PoP": round(put_pop, 1),
        })
    return pd.DataFrame(rows)


def _render_pop_table(df: "pd.DataFrame"):
    """
    Renderiza la tabla con heatmap por celda — colormap custom verde/gris/rojo
    matching el lenguaje visual del cono (tastytrade).
    """
    from matplotlib.colors import LinearSegmentedColormap
    pop_cmap = LinearSegmentedColormap.from_list(
        "ttrade_pop",
        ["#ff3366", "#3a3a3a", "#00d4aa"],
    )
    styled = (
        df.style
        .background_gradient(cmap=pop_cmap, subset=["Call PoP"], vmin=0, vmax=100)
        .background_gradient(cmap=pop_cmap, subset=["Put PoP"], vmin=0, vmax=100)
        .format({
            "Call PoP": "{:.0f}%",
            "Strike": "USD {:,.2f}",
            "Δ spot": "{:+.1f}%",
            "Put PoP": "{:.0f}%",
        })
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────
# Skew interpretation (Anthropic API)
# ─────────────────────────────────────────────
def _compute_skew_payload(K_grid, pdf_K, ticker, spot, expiry_date, dte):
    """
    Extrae stats clave de la RND al vencimiento para pasárselos al LLM.
    Devuelve dict listo para serializar a JSON, o None si la densidad es degenerada.
    """
    K_grid = np.asarray(K_grid, dtype=float)
    pdf_K = np.asarray(pdf_K, dtype=float)
    if len(K_grid) < 2:
        return None
    dx_K = float(K_grid[1] - K_grid[0])
    pdf_clean = np.clip(np.nan_to_num(pdf_K), 0, None)
    if pdf_clean.sum() <= 0 or dx_K <= 0:
        return None

    cdf_K = np.cumsum(pdf_clean) * dx_K
    if cdf_K[-1] <= 0:
        return None
    cdf_K = cdf_K / cdf_K[-1]

    def _q(level):
        idx = int(np.searchsorted(cdf_K, level))
        idx = max(0, min(idx, len(K_grid) - 1))
        return float(K_grid[idx])

    quantiles = {
        "q2p5": _q(0.025),
        "q16":  _q(0.16),
        "q50":  _q(0.50),
        "q84":  _q(0.84),
        "q97p5": _q(0.975),
    }

    if (quantiles["q97p5"] - quantiles["q2p5"]) > 0:
        skew = (
            (quantiles["q97p5"] - quantiles["q50"])
            - (quantiles["q50"] - quantiles["q2p5"])
        ) / (quantiles["q97p5"] - quantiles["q2p5"])
    else:
        skew = 0.0

    # Top dense strikes con PoP — misma lógica que los callouts del chart
    y_range = float(np.nanmax(K_grid) - np.nanmin(K_grid))
    min_spacing = max(y_range / 18.0, 1e-9)
    cone_buffer = max(y_range / 35.0, 1e-9)
    cone_edges = list(quantiles.values())

    sorted_idx = np.argsort(pdf_clean)[::-1]
    selected = []
    for idx in sorted_idx:
        if pdf_clean[idx] <= 0:
            break
        K = float(K_grid[idx])
        if any(abs(K - float(K_grid[s])) < min_spacing for s in selected):
            continue
        if any(abs(K - e) < cone_buffer for e in cone_edges):
            continue
        selected.append(idx)
        if len(selected) >= 5:
            break

    dense = []
    for idx in selected:
        K = float(K_grid[idx])
        pop = max(float(cdf_K[idx]), 1.0 - float(cdf_K[idx])) * 100.0
        dense.append({"strike": round(K, 2), "pop_pct": round(pop, 1)})

    return {
        "ticker": ticker,
        "spot": round(float(spot), 2),
        "expiry_date": str(pd.Timestamp(expiry_date).date()),
        "dte": int(dte),
        **{k: round(v, 2) for k, v in quantiles.items()},
        "skew": round(float(skew), 3),
        "dense_strikes": dense,
    }


def _stream_skew_interpretation(payload_json: str, model: str):
    """
    Generator que yieldea deltas de texto desde Anthropic streaming API.
    Permite efecto typewriter en la UI cuando se renderiza con st.empty().
    """
    import json as _json
    import os as _os
    from modules.llm_anthropic import get_anthropic_client, Anthropic as _Anthropic
    if _Anthropic is None:
        yield ("⚠️ 'anthropic' package not installed in this environment. "
               "Add `anthropic>=0.40` to requirements.txt and redeploy.")
        return
    if not (_os.getenv("ANTHROPIC_API_KEY") or "").strip():
        yield "⚠️ ANTHROPIC_API_KEY not set in this environment."
        return
    client = get_anthropic_client()
    if client is None:
        yield "⚠️ Anthropic client unavailable (unknown cause)."
        return
    p = _json.loads(payload_json)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PROMPT EDITABLE — modificá libremente para ajustar tono / foco / largo.
    # Las reglas de output (sin $, sin markdown, un párrafo) son críticas para
    # que Streamlit no interprete el texto como LaTeX/Markdown — no las quites.
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    prompt = f"""You analyze options-market data for a premium-selling trader (someone who sells short puts, short calls, or short premium spreads to collect credit on rich implied volatility). The following snapshot was extracted from the {p['ticker']} option chain via Breeden-Litzenberger (risk-neutral density at the {p['dte']}-DTE expiry on {p['expiry_date']}).

Spot price: USD {p['spot']}
Median expected price (50/50): USD {p['q50']}
68 percent confidence range: USD {p['q16']} to USD {p['q84']}
95 percent confidence range: USD {p['q2p5']} to USD {p['q97p5']}
Quantile-based skew score (in [-1, +1], negative means downside-heavy which makes put premium relatively expensive; positive means upside-heavy which makes call premium relatively expensive): {p['skew']:+}
Top density-concentration strikes with risk-neutral PoP (Probability of Profit for an OTM short option at that strike): {p['dense_strikes']}

Write the analysis as EXACTLY TWO short paragraphs separated by ONE blank line. Each paragraph must be 2 to 4 sentences.

Paragraph 1 — premium-selling overview:
- The direction and magnitude of the volatility skew, and therefore which side of the chain (puts or calls) carries the richer, fatter premium right now.
- From the dense strikes list, pick the SINGLE most attractive strike for selling premium given its PoP and its position relative to the median. Name the strike explicitly and its PoP, and label it as a short-put candidate (if below median) or a short-call candidate (if above median).

Paragraph 2 — short-put deep dive (ALWAYS include this paragraph regardless of skew direction):
- The best concrete level for selling a cash-secured short put on this expiry. Pick a strike from the dense strikes that sits below the median; if none qualifies, fall back to a level near the 16 percent or 2.5 percent quantile of the confidence range. Name the strike and its PoP.
- Why this strike makes sense for a put seller (cushion below spot, density support, PoP).
- The tail risks: estimate the percent drop from spot that would breach the short strike, and describe one or two extreme-move scenarios that would put the position in trouble (e.g., a sharp sell-off, an earnings shock, a macro event).

STRICT OUTPUT RULES — follow exactly:
- Plain text only. No headings, no bullet points, no numbered lists, no asterisks, no underscores, no backticks, no tables, no emojis, no markdown formatting of any kind.
- Do NOT use the dollar sign character at all. Write prices as 'USD 510.20' or '510.20 dollars'.
- Output EXACTLY two paragraphs separated by ONE blank line. No other line breaks within paragraphs.
- Do not label the paragraphs ("Paragraph 1", "Paragraph 2", etc.). Just write them flowing.
- Do not start with the ticker name or with a heading. Start directly with the analysis.
- Avoid jargon a retail trader cannot immediately grasp."""
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    try:
        with client.messages.stream(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if getattr(event, "type", "") == "content_block_delta":
                    delta = getattr(event.delta, "text", "")
                    if delta:
                        yield delta
                elif getattr(event, "type", "") == "message_stop":
                    break
    except Exception as e:
        yield f"⚠️ Anthropic API error: {e}"


def _render_skew_box(text: str) -> str:
    """
    Envuelve el texto en un div con estilo cyan tenue (Bloomberg/tastytrade)
    y escapa caracteres Markdown sensibles ($ * _ `) para evitar que Streamlit
    interprete el texto como LaTeX/Markdown. Preserva separación de párrafos
    convirtiendo \\n\\n en <br><br>.
    """
    safe = (
        (text or "")
        .replace("\\", "\\\\")
        .replace("$", "\\$")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
    )
    # Separación de párrafos → <br><br>; newlines simples → espacio.
    safe = safe.replace("\r\n", "\n")
    safe = safe.replace("\n\n", "<br><br>")
    safe = safe.replace("\n", " ")
    return (
        "<div style=\""
        "background-color: rgba(0, 180, 220, 0.04);"
        "border-left: 3px solid rgba(0, 180, 220, 0.35);"
        "border-radius: 4px;"
        "padding: 14px 18px;"
        "margin: 8px 0;"
        "color: #cccccc;"
        "font-family: 'Inter', -apple-system, sans-serif;"
        "font-size: 13.5px;"
        "line-height: 1.7;"
        "letter-spacing: 0.005em;"
        f"\">{safe}</div>"
    )


# ─────────────────────────────────────────────
# CACHES — Fundamentales (FMP)
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def cached_company_profile(ticker: str, fmp_key: str):
    try:
        from modules.services.company_profile_service import get_company_profile
        return get_company_profile(ticker)
    except Exception as e:
        return None


# NOTE: cached_key_metrics, cached_income_statement, cached_income_growth,
# and cached_sector_peers were removed in the MVP cleanup. They powered the
# Valuation, Financials, and Sector tabs which are no longer part of the
# app. The underlying modules.services.* code is still on disk in case we
# want to bring those analyses back later.


# ─────────────────────────────────────────────
# PAYWALL (solo producción)
# ─────────────────────────────────────────────
def _check_paywall():
    def es_usuario_pro(api_key: str) -> bool:
        if not api_key:
            return False
        return api_key.strip().upper().startswith("PRO-")

    if IS_DEV:
        return True

    with st.container():
        st.markdown("##### Pro access")
        col_key, col_cta = st.columns([2, 1])
        with col_key:
            pro_key = st.text_input("Pro API key", type="password")
        with col_cta:
            st.markdown("Don't have a key?")
            st.markdown(f"[➡ Get Pro access]({STRIPE_PAYMENT_LINK})", unsafe_allow_html=True)

        if not es_usuario_pro(pro_key):
            st.info("Enter a valid Pro key (starts with 'PRO-') to unlock.")
            return False
    return True


# ─────────────────────────────────────────────
# TAB: DENSIDADES
# ─────────────────────────────────────────────
def _metodologia_legacy():
    """
    Desarrollo del motor legacy: Breeden-Litzenberger sobre calls limpios por
    paridad, con descuento explicito por r y segunda derivada numerica.
    """
    st.markdown(r"""
We start from the option chain and build *clean* call prices.
If $C(K)$ is the call price and $P(K)$ the put price at the same strike $K$,
with spot $S_0$, risk–free rate $r$ and dividend yield $q$, we use:
""")
    st.latex(r"""
C_{\text{clean}}(K) \approx
\begin{cases}
\dfrac{\text{bid} + \text{ask}}{2} & \text{if there is a valid spread} \\
P(K) + S_0 e^{-qT} - K e^{-rT} & \text{(put–call parity)} \\
\end{cases}
""")
    st.markdown(r"Then we remove discounting:")
    st.latex(r"""
\tilde C(K) = C_{\text{clean}}(K)\, e^{rT}
\approx
\mathbb{E}_Q\big[(S_T - K)^+\big],
""")
    st.markdown(r"and we apply the Breeden–Litzenberger formula:")
    st.latex(r"f_Q(K) = \frac{\partial^2 \tilde C(K)}{\partial K^2}.")
    st.markdown(r"Numerically, we interpolate, force $f_Q(K) \ge 0$ and normalize:")
    st.latex(r"\int f_Q(K)\, dK = 1,")
    st.markdown(r"also adjusting the first moment to match the theoretical forward:")
    st.latex(r"\mathbb{E}_Q[S_T] = \int K\, f_Q(K)\, dK \approx S_0 e^{(r - q)T}.")
    st.markdown(r"On each historical date $t$ we model intraday uncertainty as a Gaussian centered at the close $S_t$:")
    st.latex(r"""
p_{\text{hist}}(s \mid t)
\propto
\exp\left(
-\frac{1}{2}\,
\frac{(s - S_t)^2}{(\sigma_{\text{hist}} S_t)^2}
\right),
""")
    st.markdown(r"with fixed $\sigma_{\text{hist}}$ relative to the price. The quantile $q_\alpha(t)$ satisfies:")
    st.latex(r"\int_{-\infty}^{q_\alpha(t)} p_t(s)\, ds = \alpha,")
    st.markdown(r"and from these we obtain the 68% and 95% confidence bands that define the probability cone shown in the chart.")


def _metodologia_forward():
    """
    Desarrollo del motor forward: sonrisa SVI libre de arbitraje bajo medida
    forward y densidad en forma cerrada. No es el mismo objeto que el legacy y
    por eso se explica aparte en vez de reusar el texto.
    """
    st.markdown(r"""
Bajo medida forward el descuento se cancela y no entra ninguna tasa. Lo primero
es leer el forward de la propia cadena, sin suponerlo: por paridad put-call
$C(K) - P(K) = e^{-rT}(F - K)$, de modo que el strike donde calls y puts cruzan
es exactamente $F$.
""")
    st.latex(r"C(K^{*}) = P(K^{*}) \;\Longrightarrow\; F = K^{*}.")
    st.markdown(r"""
Con $F$ fijo se pasa a log-moneyness $k = \ln(K/F)$ y a varianza total
implicita $w(k) = \sigma^{2}(k)\,T$, que es la variable en la que las
condiciones de no arbitraje se escriben limpio. La sonrisa se ajusta con la
parametrizacion cruda de SVI (Gatheral):
""")
    st.latex(r"""
w(k) = a + b\left[\rho\,(k - m) + \sqrt{(k - m)^{2} + \sigma^{2}}\right].
""")
    st.markdown(r"""
El ajuste se restringe a la condicion de mariposa de Durrleman, que es la que
garantiza densidad no negativa:
""")
    st.latex(r"""
g(k) = \left(1 - \frac{k\,w'(k)}{2\,w(k)}\right)^{2}
     - \frac{w'(k)^{2}}{4}\left(\frac{1}{w(k)} + \frac{1}{4}\right)
     + \frac{w''(k)}{2} \;\ge\; 0 .
""")
    st.markdown(r"""
Fuera del rango de strikes cotizados las alas se extienden con pendiente
acotada por la formula de momentos de Lee ($w'(k) \le 2$ asintoticamente), con
mezcla exponencial para que $w$, $w'$ y $w''$ queden continuas en el empalme.
Sin esa extension la malla queda truncada en los strikes observados y la masa
de cola se pierde.

Con $w$, $w'$ y $w''$ analiticas la densidad no se deriva dos veces por
diferencias finitas: sale en forma cerrada.
""")
    st.latex(r"""
p(k) = \frac{g(k)}{\sqrt{2\pi\,w(k)}}\;
       \exp\!\left(-\tfrac{1}{2}\,d_{2}^{2}\right),
\qquad
d_{2} = -\frac{k}{\sqrt{w(k)}} - \frac{\sqrt{w(k)}}{2}.
""")
    st.markdown(r"El cambio de variable a precio divide entre $K$:")
    st.latex(r"f_Q(K) = \frac{p(k)}{K}, \qquad K = F e^{k}.")
    st.markdown(r"""
Notese que la densidad es no negativa si y solo si se cumple la mariposa: el
diagnostico y el objeto son la misma cosa, en vez de que uno diga que esta bien
mientras el otro sale negativo. La verificacion que queda es la martingala,
$\mathbb{E}_Q[S_T] = F$, que el panel de diagnosticos reporta en puntos base y
que sobre catorce vencimientos da un error cuadratico medio de 1.15 pb.

Las bandas del cono se construyen igual que en el otro motor, por cuantiles de
$f_Q$ en cada fecha.
""")


def render_densidades(ticker: str):
    # Hero banner rendered later (just above the chart) replaces the old
    # st.subheader title — same message, branded layout with the icon.
    if not _check_paywall():
        st.stop()

    fmp_api_key = FMP_API_KEY
    if not fmp_api_key:
        st.error("FMP API key is not configured. Set FMP_API_KEY in your .env.")
        st.stop()
    try:
        _get_tt_token()
    except Exception as _tt_err:
        import os as _os
        def _ck(k: str) -> str:
            return "✅" if _os.environ.get(k) else "❌"
        st.error(
            "⚠️ Could not connect to tastytrade.\n\n"
            f"OAuth Personal Grant: "
            f"CLIENT_ID {_ck('TASTYTRADE_CLIENT_ID')} | "
            f"CLIENT_SECRET {_ck('TASTYTRADE_CLIENT_SECRET')} | "
            f"REFRESH_TOKEN {_ck('TASTYTRADE_REFRESH_TOKEN')}\n\n"
            f"If all three show ✅, the grant was likely revoked at "
            f"my.tastytrade.com → Manage → API Access. Generate a new one and "
            f"update the secret in Render.\n\n"
            f"Error: {_tt_err}"
        )
        st.stop()

    with st.sidebar:
        st.divider()
        st.caption("Densities")

        range_code = st.selectbox(
            "Historical range",
            options=["d1", "d5", "m1", "m3", "m6", "ytd", "y1", "y2", "y5", "max"],
            index=["d1", "d5", "m1", "m3", "m6", "ytd", "y1", "y2", "y5", "max"].index(
                settings.DEFAULT_RANGE
            ),
            key="dens_range",
        )

        available_expiries: list[str] = []
        if ticker:
            try:
                available_expiries = cached_expiries(ticker)
            except RuntimeError as e:
                st.warning(str(e))
                available_expiries = []

        if available_expiries:
            # Reloj de Nueva York, no el de la maquina. El DTE de un
            # vencimiento es un hecho del mercado, y en un servidor en UTC el
            # dia cambia a las 19:00 hora de Nueva York: el 0DTE aparecia como
            # vencido durante las ultimas horas de la tarde.
            today = (pd.Timestamp.now(tz="America/New_York")
                     .normalize().tz_localize(None))
            expiry_dates = []
            for s in available_expiries:
                try:
                    expiry_dates.append(pd.to_datetime(s))
                except Exception:
                    expiry_dates.append(None)

            best_idx = None
            best_distance = None
            for idx, dt in enumerate(expiry_dates):
                if dt is None:
                    continue
                days = (dt - today).days
                # Default del vencimiento: el mas cercano a 45 dias. Decidido el
                # 1 de septiembre de 2026: 45 dias es el ancla estandar de mesa
                # para venta de prima, y es la misma que usa el ranking para el
                # sesgo a 25 deltas.
                if days < 21 or days > 75:
                    continue
                distance = abs(days - 45)
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_idx = idx

            if best_idx is None:
                for idx, dt in enumerate(expiry_dates):
                    if dt is None:
                        continue
                    if (dt - today).days >= 7:
                        best_idx = idx
                        break

            if best_idx is None:
                best_idx = len(available_expiries) - 1

            dte_by_expiry: dict[str, int] = {}
            for s, dt in zip(available_expiries, expiry_dates):
                if dt is not None:
                    dte_by_expiry[s] = (dt - today).days

            from modules import expiraciones as _exp_mod

            def _fmt_expiry(s: str) -> str:
                """
                Semanal, mensual y trimestral no son lo mismo: el interes
                abierto de un mensual es de otro orden y es el que acumula
                posicion estructural. Leer un GEX de semanal como si fuera de
                mensual lleva a sobreestimar la fuerza del muro.
                """
                days = dte_by_expiry.get(s)
                try:
                    return _exp_mod.etiqueta(s, days)
                except Exception:
                    return s if days is None else f"{s}  ·  {days} DTE"

            expiry_str = st.selectbox(
                "Expiry",
                options=available_expiries,
                index=best_idx,
                key="dens_expiry",
                format_func=_fmt_expiry,
            )
        else:
            expiry_str = st.text_input("Expiry (YYYY-MM-DD)", value="2025-12-19", key="dens_expiry_manual")

        # Se DESCARGA un anio (Historical range arriba) pero se MUESTRAN 60 dias
        # por defecto. Medido sobre la lamina del 2 de septiembre de 2026 con un
        # anio visible: la historia ocupaba el 55% del ancho, la zona de GEX el
        # 16% y el vacio de la derecha el 29%. El sujeto de la lamina vivia en
        # una sexta parte del lienzo. Subiendo este numero se recupera el anio
        # completo cuando se quiere contexto de regimen.
        past_days = st.number_input("Historical window (days)", min_value=20,
                                    max_value=2000, value=60, step=10,
                                    key="dens_past",
                                    help="Dias de historia VISIBLES. La descarga "
                                         "sigue siendo la del rango de arriba.")

        # ── Alcance de los muros de GEX ────────────────────────────────────
        # "todos" cuelga un histograma de cada vencimiento entre hoy y el
        # elegido, que es la estructura temporal del posicionamiento: se ve
        # como se mueve el muro a lo largo del plazo, que es informacion que
        # una lamina de un solo vencimiento no puede dar. Cuesta una llamada de
        # red por vencimiento en la primera carga.
        # El default sale del entorno para poder desplegar en Render con la
        # vista ligera sin tocar codigo: alla cada sesion nueva pagaria las
        # llamadas de red de todos los vencimientos.
        _ALCANCES = ["todos", "0DTE + elegido"]
        _alc_env = os.getenv("PROBEDGE_GEX_ALCANCE", "todos").strip()
        gex_alcance = st.radio(
            "Muros de GEX",
            options=_ALCANCES,
            index=_ALCANCES.index(_alc_env) if _alc_env in _ALCANCES else 0,
            key="gex_alcance",
            horizontal=True,
            help=("todos: un histograma por vencimiento hasta el elegido, con "
                  "el ancho de cada uno limitado por la distancia al anterior. "
                  "0DTE + elegido: solo dos capas, mas limpio y mas rapido."),
        )

        # ── Interruptor de motor de densidad ───────────────────────────────
        # Default desde el entorno (PROBEDGE_RND), sobreescribible en vivo para
        # poder comparar los dos conos sin reiniciar. `legacy` es el default para
        # que lo desplegado no cambie de comportamiento sin decision explicita.
        # El selector de motor se dibuja arriba de la grafica, junto al
        # interruptor del heatmap, porque son los dos controles que cambian lo
        # que se ve. Aqui solo se fija el default y se lee el valor vigente:
        # Streamlit vuelve a correr el script completo al cambiarlo, asi que el
        # valor esta disponible antes de calcular la densidad.
        _default_mode = os.getenv("PROBEDGE_RND", "legacy").strip().lower()
        if _default_mode not in rnd_bridge.MODES:
            _default_mode = "legacy"
        if "dens_engine" not in st.session_state:
            st.session_state["dens_engine"] = _default_mode
        rnd_mode = st.session_state["dens_engine"]

        r_rate = st.number_input(
            "Risk-free rate (r, annual)",
            value=float(settings.DEFAULT_RATE), step=0.005, format="%.3f",
            key="dens_r",
            disabled=(rnd_mode == "forward"),
            help=("No aplica en modo forward: el descuento se cancela bajo medida "
                  "forward y el forward se lee del cruce call-put."),
        )
        if rnd_mode == "forward":
            st.caption("r sin efecto en modo forward.")
        # Dividend yield (q) eliminado del UI — se asume 0 por simplicidad.
        q_rate = 0.0

    # El interruptor del heatmap se dibuja arriba de la grafica, junto al
    # selector de motor. Aqui solo se lee el valor vigente, porque la lamina se
    # construye antes de llegar a esa fila en el flujo del script.
    if "chk_density_heatmap" not in st.session_state:
        st.session_state["chk_density_heatmap"] = False
    show_heatmap = st.session_state["chk_density_heatmap"]

    hist_sigma_rel = float(settings.HIST_SIGMA_REL)
    st.caption("Data: tastytrade (options · real-time) · FMP (historical OHLCV)")
    # Declarar la proporcion entre lo descargado y lo dibujado. Sin esto no hay
    # forma de notar que se estan pidiendo cinco anios para mostrar sesenta
    # dias, que es lo que estaba pasando.
    _dias_desc = {"d1": 1, "d5": 5, "m1": 21, "m3": 63, "m6": 126, "ytd": 252,
                  "y1": 252, "y2": 504, "y5": 1260, "max": 0}.get(range_code, 252)
    _desc_txt = "todo el historico" if _dias_desc == 0 else f"{_dias_desc} sesiones"
    st.caption(f"Historico: se descargan {_desc_txt} (`{range_code}`) y se "
               f"dibujan los ultimos {int(past_days)} dias naturales. "
               f"Sube la ventana en la barra lateral para ver mas contexto de "
               f"regimen sin volver a descargar.")

    try:
        quotes_df = cached_quotes(
            ticker, range_code, fmp_api_key, datetime.now().date().isoformat()
        )
    except RuntimeError as e:
        st.error(f"Could not download historical data from FMP: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        st.stop()

    if quotes_df.empty:
        st.error("No historical data for that ticker / range.")
        st.stop()

    valuation_date = quotes_df["Date"].max()
    try:
        spot_q = get_quotes_from_env([ticker])
        if spot_q.get(ticker, {}).get("price"):
            spot = float(spot_q[ticker]["price"])
        else:
            spot = float(quotes_df.loc[quotes_df["Date"] == valuation_date, "Close"].iloc[0])
    except Exception:
        spot = float(quotes_df.loc[quotes_df["Date"] == valuation_date, "Close"].iloc[0])

    try:
        expiry_date = pd.to_datetime(expiry_str)
    except Exception:
        st.error("Invalid expiry date format.")
        st.stop()

    # Forward window = DTE (días hasta expiración). El cono termina exactamente
    # en la fecha de vencimiento elegida; mínimo 7 días para evitar ventanas degeneradas.
    future_days = max(7, int((expiry_date - valuation_date).days))

    try:
        options_df = cached_options(ticker, expiry_str)
    except RuntimeError as e:
        st.error(f"Could not download options chain: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        st.stop()

    if options_df is None or options_df.empty:
        st.warning(f"No options data for **{ticker}** expiry **{expiry_str}**. Try a different expiry.")
        st.stop()

    try:
        K_grid, pdf_K, rnd_diag = rnd_bridge.density(
            options_df, spot=spot, valuation_date=valuation_date,
            expiry_date=expiry_date, r_annual=r_rate, q_annual=q_rate,
            mode=rnd_mode,
        )
    except Exception as e:
        st.error(f"Could not build RND ({rnd_mode}): {e}")
        if rnd_mode == "forward":
            st.info("Cambia el motor a `legacy` en la barra lateral para seguir "
                    "trabajando mientras se revisa la cadena de este vencimiento.")
        st.stop()

    rnd_by_date = {pd.Timestamp(expiry_date): (K_grid, pdf_K)}

    dates_all, price_grid, density = build_time_price_density(
        quotes_df, rnd_by_date, hist_sigma_rel=hist_sigma_rel, interpolate_future=True,
    )

    min_date = valuation_date - pd.Timedelta(days=int(past_days))
    max_date = valuation_date + pd.Timedelta(days=int(future_days))
    mask = (dates_all >= np.datetime64(min_date)) & (dates_all <= np.datetime64(max_date))

    if mask.sum() == 0:
        st.warning("Selected window does not overlap available data.")
        st.stop()

    dates_win = dates_all[mask]
    density_win = density[:, mask]
    expiry_dates_win = [
        d for d in rnd_by_date.keys()
        if pd.Timestamp(min_date) <= pd.Timestamp(d) <= pd.Timestamp(max_date)
    ]

    # ─── Hero banner ───────────────────────────────────────────────────────
    # Renders inline above the chart: the brand icon (cone of probability)
    # on the left and the wordmark + tagline on the right. The icon SVG is
    # embedded literally (not via st.image) so that strokes/gradients render
    # at full quality without raster downsampling, and so the visual loads
    # in the same DOM pass as the rest of the page (no flicker).
    #
    # IMPORTANT: we strip the XML declaration and any pre-SVG comments from
    # the file before injecting into st.markdown. The browser's HTML parser
    # treats `<?xml ... ?>` as a "bogus comment" and bleeds the surrounding
    # text into the visible DOM — that produced the broken sidebar columns
    # in the first attempt. Pulling just the `<svg>...</svg>` element is the
    # safe form.
    # Build the icon as a base64-encoded data URI inside an <img> tag.
    # Inline <svg> embedding inside Streamlit's markdown container was
    # producing collapsed-to-zero icons because of flex-sizing dependency
    # loops between the SVG's viewBox and its parent's intrinsic width.
    # A data URI <img> sidesteps all of that — the browser treats it as a
    # replaced element with fixed dimensions, exactly like a PNG would
    # behave. Reliable across every browser and Streamlit version.
    import base64 as _base64
    import re as _re
    try:
        _raw_svg = ICON_PATH.read_text(encoding="utf-8")
        _svg_match = _re.search(r"<svg\b.*?</svg>", _raw_svg, _re.DOTALL | _re.IGNORECASE)
        _svg_only = _svg_match.group(0) if _svg_match else ""
        _icon_data_uri = (
            "data:image/svg+xml;base64,"
            + _base64.b64encode(_svg_only.encode("utf-8")).decode("ascii")
        ) if _svg_only else ""
    except Exception:
        _icon_data_uri = ""
    if _icon_data_uri:
        st.markdown(
            f"""
            <div style="
                display: flex;
                align-items: center;
                gap: 22px;
                padding: 18px 24px;
                margin: 4px 0 18px 0;
                border-radius: 10px;
                background: linear-gradient(180deg, rgba(0,180,220,0.04) 0%, rgba(0,0,0,0.0) 100%);
                border-left: 2px solid rgba(0, 180, 220, 0.35);
            ">
                <img src="{_icon_data_uri}" width="72" height="72" alt="ProbEdge"
                     style="flex: 0 0 auto; display: block;"/>
                <div style="flex: 1 1 auto; min-width: 0;">
                    <div style="
                        font-family: 'Inter', -apple-system, sans-serif;
                        font-size: 28px;
                        font-weight: 600;
                        letter-spacing: -0.01em;
                        line-height: 1.05;
                        color: #f0fbff;
                        margin: 0 0 6px 0;
                    ">ProbEdge</div>
                    <div style="
                        font-family: 'Inter', -apple-system, sans-serif;
                        font-size: 13px;
                        font-weight: 400;
                        letter-spacing: 0.01em;
                        color: #8aa9b3;
                        margin: 0;
                    ">Risk-Neutral Density · Live from the option chain</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ─── Company teaser — short context above the chart ─────────────────────
    # Positioned narratively between the ProbEdge brand banner and the chart:
    # the reader first sees "this is ProbEdge", then "this ticker is XYZ
    # (sector, industry), and here's what they do", and only then the chart.
    # Short and efficient: just the first ~280 chars of FMP's description,
    # truncated at a sentence boundary. The detailed deep-dive (logo + facts
    # + Claude-translated long description) still lives below the chart.
    if FMP_API_KEY and ticker:
        try:
            _teaser_profile = cached_company_profile(ticker, FMP_API_KEY)
        except Exception:
            _teaser_profile = None
        if _teaser_profile is not None:
            _t_logo = (
                getattr(_teaser_profile, "logo_url", None)
                or getattr(_teaser_profile, "image_url", None)
            )
            _t_name = getattr(_teaser_profile, "name", None) or ticker
            _t_sector = getattr(_teaser_profile, "sector", None) or ""
            _t_industry = getattr(_teaser_profile, "industry", None) or ""
            _t_desc = getattr(_teaser_profile, "description_en", None) or ""

            # Trim description to ~280 chars at sentence boundary for a punchy preview.
            if _t_desc:
                _TMAX = 280
                if len(_t_desc) > _TMAX:
                    _t_cut = _t_desc[:_TMAX]
                    _t_stop = max(
                        _t_cut.rfind(". "),
                        _t_cut.rfind("? "),
                        _t_cut.rfind("! "),
                    )
                    if _t_stop < 140:
                        _t_stop = _t_cut.rfind(" ")
                    _t_short = (_t_cut[: _t_stop + 1] if _t_stop > 0 else _t_cut) + "…"
                else:
                    _t_short = _t_desc
            else:
                _t_short = ""

            _t_sector_line = " · ".join([x for x in [_t_sector, _t_industry] if x])
            _t_logo_html = (
                f'<img src="{_t_logo}" alt="{_t_name}" '
                f'style="width: 52px; height: 52px; object-fit: contain; '
                f'flex: 0 0 auto; border-radius: 6px; background: #0a0a0a; '
                f'padding: 2px;"/>'
            ) if _t_logo else ""

            st.markdown(
                f"""
                <div style="
                    display: flex;
                    align-items: flex-start;
                    gap: 16px;
                    padding: 8px 6px 18px 6px;
                    margin: 0 0 14px 0;
                ">
                    {_t_logo_html}
                    <div style="flex: 1 1 auto; min-width: 0;">
                        <div style="
                            font-family: 'Inter', -apple-system, sans-serif;
                            font-size: 16px;
                            font-weight: 600;
                            color: #e8f4f7;
                            line-height: 1.25;
                            margin: 0 0 3px 0;
                        ">{_t_name}</div>
                        <div style="
                            font-family: 'Inter', -apple-system, sans-serif;
                            font-size: 12px;
                            color: #7a96a0;
                            margin: 0 0 8px 0;
                        ">{_t_sector_line}</div>
                        <div style="
                            font-family: 'Inter', -apple-system, sans-serif;
                            font-size: 13.5px;
                            color: #b5cdd4;
                            line-height: 1.6;
                            margin: 0;
                        ">{_t_short}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ─── Muros de GEX para colgar del cono ───────────────────────────────────
    # Se calculan ANTES de la grafica porque la lamina los necesita. El panel de
    # detalle mas abajo reutiliza este mismo resultado en vez de recalcularlo.
    _gp = _tc = None
    _gex_chains, _gex_Ts, _gex_fits, _gex_fwds = {}, {}, {}, {}
    _gex_pan, _gex_capas, _gex_exps = None, None, {}
    try:
        from modules import gex_panel as _gp
        from modules import time_clock as _tc
        _fuente_exp = available_expiries if available_expiries else [expiry_str]
        if gex_alcance == "todos":
            _sel = _gp.todos_los_vencimientos(_fuente_exp, valuation_date,
                                              hasta=expiry_str)
        else:
            _sel = _gp.pick_expiries(_fuente_exp, valuation_date,
                                     selected=expiry_str)
        _ahora = pd.Timestamp.now(tz="America/New_York")
        with st.spinner(f"Cadenas de {len(_sel)} vencimientos para los muros de GEX..."):
            for _etiq, _exp in _sel.items():
                try:
                    _df = cached_options(ticker, str(_exp.date()))
                except Exception:
                    continue
                if _df is None or _df.empty:
                    continue
                _tk = _tc.time_to_expiry(_ahora, _exp)
                if _tk["expired"]:
                    continue
                _gex_chains[_etiq] = _df
                _gex_Ts[_etiq] = _tk["T"]
                _gex_exps[_etiq] = _exp
                # El ajuste SVI solo se necesita para la correccion de sonrisa,
                # que se aplica al plazo principal. Con dieciseis vencimientos,
                # calibrarlos todos cuesta segundos y no se usa ninguno salvo
                # el elegido y el 0DTE.
                if _etiq not in ("0DTE",) and _exp != pd.Timestamp(expiry_str).normalize():
                    continue
                try:
                    _r = rnd_bridge.to_rnd_frame(_df)
                    _res = rnd_forward_mod.rnd(_r, spot, _tk["T"], smile_model="svi")
                    if _res:
                        _sm = rnd_forward_mod.fit_smile(_r, _res["forward"], model="svi", T=_tk["T"])
                        _gex_fits[_etiq] = (_sm or {}).get("svi")
                        _gex_fwds[_etiq] = _res["forward"]
                except Exception:
                    pass
        if _gex_chains:
            _gex_pan = _gp.compute(_gex_chains, spot, ticker, _gex_Ts)
            _niv = {}
            for _, _f in _gex_pan["filas"].iterrows():
                _n = {"call_wall": _f["call_wall"], "put_wall": _f["put_wall"],
                      "gamma_flip": _f["flip"], "max_pain": _f["max_pain"]}
                # El MVC absoluto suele quedar muy dentro del dinero por el
                # valor intrinseco, fuera de la banda de la lamina. El que se
                # dibuja es el fuera del dinero, que es el que responde a donde
                # esta el dinero apostado.
                if pd.notna(_f.get("mvc_otm_strike")):
                    _n["mvc"] = _f["mvc_otm_strike"]
                    _n["mvc_tipo"] = str(_f.get("mvc_otm_tipo", ""))
                _niv[_f["plazo"]] = _n
            _gex_capas = _gp.capas_overlay(_gex_pan["tablas"], _gex_exps,
                                           niveles=_niv, spot=spot)
    except Exception as _e:
        st.caption(f"Muros de GEX no disponibles en el cono: {_e}")

    # ─── Alerta de regimen de gamma ──────────────────────────────────────────
    # Va antes de la grafica porque es la lectura que condiciona todo lo demas.
    # Gamma negativo significa que la cobertura del dealer va en el sentido del
    # movimiento y lo amplifica; positivo significa que va en contra y lo
    # amortigua. El signo del dealer es una convencion declarada, no una
    # medicion: OPRA no publica lado de la operacion.
    if _gex_pan is not None and not _gex_pan["filas"].empty:
        _pr = _gex_pan["filas"].iloc[-1]
        for _, _f in _gex_pan["filas"].iterrows():
            if str(_f["plazo"]).startswith("elegido"):
                _pr = _f
                break
        _neto = float(_pr["gex_neto_M"])
        _flip = _pr.get("flip")
        _negativo = _neto < 0
        _col = "#d95926" if _negativo else "#199e70"
        _titulo = ("GAMMA NEGATIVO · la cobertura amplifica el movimiento"
                   if _negativo else
                   "GAMMA POSITIVO · la cobertura amortigua el movimiento")
        _dist = ""
        if _flip is not None and pd.notna(_flip) and spot:
            _pct = (spot - float(_flip)) / float(_flip) * 100.0
            _lado = "arriba" if _pct >= 0 else "abajo"
            _dist = (f"Spot {spot:,.2f}, {abs(_pct):.2f}% {_lado} del flip en "
                     f"{float(_flip):,.2f}.")
        # ── El iman, medido ────────────────────────────────────────────────
        # Un muro atrae si el gamma en el spot es positivo Y el mercado
        # descuenta llegar ahi. La segunda condicion se mide con la densidad,
        # que ya tenemos: es la pieza que ningun proveedor de GEX publica.
        _iman_txt = ""
        try:
            from modules import iman as _im
            _paso = 1.0
            _tab_pr = (_gex_pan["tablas"] or {}).get(_pr["plazo"])
            if _tab_pr is not None and len(_tab_pr) > 1:
                _paso = float(np.median(np.diff(_tab_pr.index.to_numpy(float))))
            _pmax = _im.pin_maximo(K_grid, pdf_K, paso=_paso)
            _filas_iman = []
            for _nom, _val in (("call wall", _pr.get("call_wall")),
                               ("put wall", _pr.get("put_wall")),
                               ("max pain", _pr.get("max_pain"))):
                if _val is None or not pd.notna(_val):
                    continue
                _pp = _im.probabilidad_de_pin(K_grid, pdf_K, float(_val), paso=_paso)
                _sg = _im.distancia_en_sigmas(K_grid, pdf_K, spot, float(_val))
                _cl = _im.clasificar_nivel(float(_val), spot, _neto, _pp,
                                           prob_max=_pmax)
                _filas_iman.append(
                    f"{_nom} {float(_val):,.0f}: "
                    f"{'n/d' if _pp is None else format(_pp * 100, '.1f') + '%'} de pin, "
                    f"{'n/d' if _sg is None else format(_sg, '+.2f')} sigmas, {_cl}")
            if _filas_iman:
                _iman_txt = "  ·  ".join(_filas_iman)
        except Exception:
            _iman_txt = ""

        _mvc_txt = ""
        if pd.notna(_pr.get("mvc_otm_strike")):
            _mvc_txt = (f" MVC fuera del dinero: {_pr['mvc_otm_strike']:,.0f}"
                        f"{_pr.get('mvc_otm_tipo','')} con "
                        f"{_pr['mvc_otm_prima_M']:,.1f} M de prima viva.")
        st.markdown(
            f"""
            <div style="
                border-left: 4px solid {_col};
                background: linear-gradient(90deg, {_col}22 0%, rgba(0,0,0,0) 70%);
                padding: 12px 16px; margin: 4px 0 14px 0; border-radius: 4px;">
              <div style="font-family:'JetBrains Mono',monospace; font-size:16px;
                          font-weight:600; color:{_col}; letter-spacing:0.02em;">
                {_titulo}
              </div>
              <div style="font-family:'JetBrains Mono',monospace; font-size:14px;
                          color:#c3c2b7; margin-top:6px;">
                {_pr['plazo']} · GEX neto {_neto:,.0f} M USD por movimiento de 1%.
                {_dist}{_mvc_txt}
              </div>
              <div style="font-family:'JetBrains Mono',monospace; font-size:13px;
                          color:#8f8f88; margin-top:6px;">
                {_iman_txt}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ─── Controles de la grafica ─────────────────────────────────────────────
    # Los dos controles que cambian lo que se ve van juntos y antes de la
    # grafica, no despues: quien llega a la lamina primero encuentra con que
    # modificarla. El heatmap enciende la capa de densidad; el motor decide con
    # que metodo se calculo esa densidad, y por eso ambos mandan sobre la misma
    # imagen.
    st.markdown(
        """
        <style>
        [data-testid="stVerticalBlockBorderWrapper"] {
            width: fit-content !important;
            max-width: 100% !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _ctl_l, _ctl_c, _ctl_r = st.columns([1, 3, 1])
    with _ctl_c:
        with st.container(border=True):
            _c_heat, _c_eng = st.columns([1, 1.4])
            with _c_heat:
                st.toggle(
                    "Show density heatmap",
                    key="chk_density_heatmap",
                    help="Overlay the implied probability density as a color "
                         "heatmap. Brighter colors = more probability mass "
                         "concentrated at that price level on that date.",
                )
            with _c_eng:
                st.radio(
                    "RND engine",
                    options=list(rnd_bridge.MODES),
                    key="dens_engine",
                    help=("legacy: segunda derivada sobre calls limpios por "
                          "paridad, el camino historico de la app. forward: "
                          "medida forward, forward por cruce call-put, sonrisa "
                          "ajustada y extension de cola acotada por Lee."),
                    horizontal=True,
                )

    _fig_cono = plot_main_figure(
        quotes_df, dates_win, price_grid, density_win,
        expiry_dates=expiry_dates_win, valuation_date=valuation_date,
        show_heatmap=show_heatmap,
        gex_capas=_gex_capas,
    )
    _y_rango = _fig_cono.get("y_rango") if isinstance(_fig_cono, dict) else None

    # ─── Diagnosticos del motor de densidad ──────────────────────────────────
    # Solo en modo forward hay diagnosticos que auditar: el legacy no cumple la
    # condicion de martingala por construccion, asi que no hay nada que medir
    # contra la superficie. Este panel es el que permite decidir si la densidad
    # que se esta viendo es publicable o no.
    with st.expander(f"RND diagnostics — engine: {rnd_mode}", expanded=False):
        if rnd_diag.get("mode") == "legacy":
            st.caption(rnd_diag.get("nota", ""))
            st.caption(
                "Cambia el motor a `forward` en la barra lateral para ver el cono "
                "con la densidad corregida y sus diagnosticos."
            )
        else:
            d = rnd_diag
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Forward (cruce C-P)", f"{d['forward']:.2f}",
                      f"{d['basis_bp']:+.0f} pb vs spot")
            c2.metric("Media vs forward", f"{d['mean_vs_forward_bp']:+.2f} pb",
                      help="Condicion de martingala. Medido: rmse de 1.15 pb sobre "
                           "14 vencimientos. Por encima de ~5 pb, revisar la cadena.")
            c3.metric("Integral", f"{d['integral']:.4f}")
            c4.metric("R2 de la sonrisa", f"{d['smile_r2']:.4f}",
                      f"{d['smile_points']} puntos")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("IV ATM", f"{d['atm_iv']*100:.2f}%")
            c2.metric("MFIV (swap de varianza)",
                      f"{d['mfiv']*100:.2f}%" if d.get("mfiv") else "n/d",
                      help="Es la medida que usa el ranking. Domina a la ATM cuando "
                           "hay sesgo y convexidad.")
            c3.metric("Desv / lognormal", f"{d['sd_ratio_lognormal']:.3f}",
                      help="Con sesgo y colas gruesas debe estar por encima de 1. "
                           "Medido entre 1.06 y 1.15.")
            c4.metric("Cola vs lognormal",
                      f"{d['tail_ratio']:.2f}x" if d.get("tail_ratio") else "n/d",
                      help="Masa mas alla de 2 sigmas contra la lognormal de la "
                           "misma IV ATM.")

            st.markdown("**Procedencia de cada momento.** Fraccion que aporta la "
                        "region extrapolada. Un momento por encima de 50% es salida "
                        "del modelo de cola, no lectura del mercado.")
            pub = d["publishable"]
            st.dataframe(pd.DataFrame([
                {"momento": "media",     "extrapolado": f"{d['share_extrap_m1']*100:5.1f}%", "publicable": pub["mean"]},
                {"momento": "desviacion","extrapolado": f"{d['share_extrap_m2']*100:5.1f}%", "publicable": pub["sd"]},
                {"momento": "sesgo",     "extrapolado": f"{d['share_extrap_m3']*100:5.1f}%", "publicable": pub["skew"]},
                {"momento": "curtosis",  "extrapolado": f"{d['share_extrap_m4']*100:5.1f}%", "publicable": pub["kurtosis"]},
            ]), hide_index=True, width="stretch")

            st.caption(
                f"Cobertura de strikes observada: {d['sigma_obs_low']:.1f} a "
                f"{d['sigma_obs_high']:+.1f} sigmas. "
                f"Masa en cola extrapolada: {d['mass_tail_left']*100:.2f}% izquierda, "
                f"{d['mass_tail_right']*100:.2f}% derecha. "
                f"Pendientes de ala (cota de Lee, 2): {d['beta_L']:.3f} y {d['beta_R']:.3f}."
            )
            if d.get("parity_slope") is not None:
                st.caption(
                    f"Consistencia de cotizaciones: la pendiente de C-P contra K es "
                    f"{d['parity_slope']:.4f} y deberia ser exactamente -1. "
                    f"El forward por regresion se separa {d['forward_gap_bp']:+.1f} pb "
                    f"del forward por cruce. Es el piso de ruido del dato, no error de metodo."
                )
            st.caption(rnd_diag.get("nota", ""))

    # ─── Panel de Gamma Exposure ─────────────────────────────────────────────
    # El detalle por strike, con el eje de GEX en millones y los niveles
    # numericos. Los muros ya se vieron colgados del cono; aqui se leen las
    # magnitudes. Son la misma tabla vista con dos propositos distintos.
    try:
        if _gex_chains:
            _gp.render(_gex_chains, spot, ticker, _gex_Ts, valuation_date,
                       svi_fits=_gex_fits, forwards=_gex_fwds,
                       pan_previo=_gex_pan, y_rango=_y_rango)
        else:
            st.info("No hay cadenas utilizables para el panel de Gamma Exposure.")
    except Exception as _e:
        st.warning(f"El panel de Gamma Exposure no se pudo construir: {_e}")

    # ─── Skew interpretation via Claude (streaming typewriter) ───
    skew_payload = _compute_skew_payload(
        K_grid, pdf_K, ticker, spot, expiry_date, future_days,
    )
    if skew_payload is not None:
        st.divider()
        st.subheader("Skew interpretation")

        import json as _json
        import hashlib as _hashlib

        payload_str = _json.dumps(skew_payload, sort_keys=True)
        payload_hash = _hashlib.md5(payload_str.encode()).hexdigest()
        cache = st.session_state.setdefault("_skew_cache", {})
        placeholder = st.empty()

        if payload_hash in cache:
            # Ya se streameó este payload en la sesión — render estático.
            placeholder.markdown(
                _render_skew_box(cache[payload_hash]),
                unsafe_allow_html=True,
            )
        else:
            # Primera vez para este payload — typewriter desde Anthropic.
            chunks: list[str] = []
            for chunk in _stream_skew_interpretation(payload_str, ANTHROPIC_MODEL):
                chunks.append(chunk)
                placeholder.markdown(
                    _render_skew_box("".join(chunks)),
                    unsafe_allow_html=True,
                )
            cache[payload_hash] = "".join(chunks)

        st.caption(
            "† This interpretation is AI-generated commentary on a risk-neutral "
            "probability study derived from option-chain prices. It is not "
            "financial advice nor a recommendation to trade — use at your own risk."
        )

    # ─── PoP table (premium-selling reference) ───
    df_pop = _build_pop_table(K_grid, pdf_K, spot)
    if df_pop is not None:
        st.divider()
        st.subheader("PoP table — premium-selling reference")
        _render_pop_table(df_pop)
        st.caption(
            "Each row pairs a strike (sampled at fixed CDF levels of the RND at "
            "expiry) with the risk-neutral PoP of a short call (left) and a "
            "short put (right). Greener cells mean a higher probability the "
            "option expires OTM, i.e. the short keeps the full premium."
        )

    # ─── Explanation & Math ───
    # La explicacion cierra el circuito con los dos controles de arriba: el
    # texto describe el metodo que efectivamente produjo la lamina que se acaba
    # de ver, no un metodo generico. Cambiar el motor cambia esta seccion.
    st.subheader("Explanation")
    if rnd_mode == "forward":
        st.info(
            "Motor activo: **forward**. La densidad se obtiene de una sonrisa "
            "SVI libre de arbitraje bajo medida forward, en forma cerrada. El "
            "desarrollo de abajo corresponde a este motor."
        )
    else:
        st.info(
            "Motor activo: **legacy**. La densidad se obtiene por segunda "
            "derivada numerica sobre calls limpios por paridad, descontando con "
            "r. El desarrollo de abajo corresponde a este motor. Cambia el motor "
            "arriba de la grafica para ver el otro."
        )
    st.markdown(r"""
This chart shows how the options market assigns probabilities to different price levels over time.
The heatmap translates those probabilities into colors so you can see where probability mass is concentrated.

Each point in the time–price plane in the future has an associated density: if the color is very faint,
the market sees that scenario as unlikely; if the color is more intense, many price paths compatible with
current option prices pass through that region.

Historical candles show the prices that actually occurred in the past, while the cone and heatmap show
which combinations of date and price are consistent with option prices under the risk–neutral measure.

You can think of an entire swarm of possible future price paths: the heatmap highlights in brighter colors
the zones where more trajectories accumulate, according to option prices, and leaves almost black the zones
where almost no simulated path arrives.

For example, if 60 days from now the brightest area is near a price of 420, this means that, under the market's
risk–neutral view, it is more likely to find the price around 420 than far above or below that value, and the
68% and 95% bands indicate ranges where most of that probability is concentrated.

Working with implied densities instead of a single "target price" lets you evaluate tail risk, asymmetries
and extreme scenarios, which makes this visualization especially useful to design strategies, size positions,
and understand how the market is pricing future uncertainty.
""")

    # Methodology section is visually separated from the prose explanation:
    # collapsed by default so readers who only want the visual picture aren't
    # buried in formulas, but one click reveals the full Breeden–Litzenberger
    # derivation for the quantitatively inclined.
    with st.expander("Mathematical summary of the methodology", expanded=False):
        if rnd_mode == "forward":
            _metodologia_forward()
        else:
            _metodologia_legacy()


# ─────────────────────────────────────────────
# TAB: COMPANY
# ─────────────────────────────────────────────
def render_empresa(ticker: str):
    st.subheader(f"🏢 Company Profile — {ticker}")

    if not FMP_API_KEY:
        st.error("FMP_API_KEY is not set.")
        return

    with st.spinner(f"Loading profile for {ticker}..."):
        profile = cached_company_profile(ticker, FMP_API_KEY)

    if profile is None:
        st.error(f"Could not fetch profile for **{ticker}**. Check the ticker or FMP connectivity.")
        return

    # Mostrar logo si disponible
    logo = getattr(profile, "logo_url", None) or getattr(profile, "image_url", None)
    name = getattr(profile, "name", None) or ticker
    sector = getattr(profile, "sector", None) or "N/A"
    industry = getattr(profile, "industry", None) or "N/A"
    website = getattr(profile, "website", None) or ""
    description_en = getattr(profile, "description_en", None) or ""

    col_logo, col_info = st.columns([1, 4])
    with col_logo:
        if logo:
            try:
                st.image(logo, width=80)
            except Exception:
                pass
    with col_info:
        st.markdown(f"### {name} (`{ticker}`)")
        st.caption(f"**Sector:** {sector} · **Industry:** {industry}")
        if website:
            st.caption(f"[{website}]({website})")

    # Facts básicos (market cap, etc.)
    facts = getattr(profile, "facts", None)
    if facts:
        cols = st.columns(4)
        items = list(facts.items())
        for i, (k, v) in enumerate(items[:8]):
            with cols[i % 4]:
                st.metric(k, v)

    st.divider()

    # Business description (LLM streaming summary)
    st.markdown("#### Business Description")

    if not description_en:
        st.info("No description available for this ticker on FMP.")
        return

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        st.warning("⚠️ ANTHROPIC_API_KEY not set — showing raw FMP description.")
        st.markdown(description_en[:800] + ("..." if len(description_en) > 800 else ""))
        return

    try:
        from modules.llm_anthropic import stream_translate_and_summarize
        desc_placeholder = st.empty()
        buffer = ""
        for chunk in stream_translate_and_summarize(
            english_text=description_en,
            sector=sector,
            model=ANTHROPIC_MODEL,
            max_words=120,
        ):
            buffer += chunk
            desc_placeholder.markdown(buffer + "▌")
        desc_placeholder.markdown(buffer)
    except Exception as e:
        st.warning(f"Claude analysis error: {e}")
        st.markdown(description_en[:800])


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    # Single-page MVP layout:
    #   sidebar → header (ProbEdge wordmark) + Ticker input + company snapshot
    #   main flow → render_densidades (hero banner + chart + heatmap toggle +
    #                                   skew interpretation + methodology expander)
    #             → divider
    #             → render_empresa (company logo + facts + AI description)
    #             → sidebar footer (data attribution)
    #
    # Tabs (Valuation / Financials / Sector) were removed during MVP cleanup
    # — only Densities and Company remain, fused into one continuous scroll.
    with st.sidebar:
        st.markdown("## ProbEdge")
        global_ticker = st.text_input(
            "Ticker",
            value="SPY",
            key="global_ticker",
            help="Ticker driving the chart and the company snapshot.",
        ).upper().strip()

        # Company name + short profile (FMP). Cached → only one call per ticker.
        # Renders silently if FMP key or profile is unavailable, so the sidebar
        # never breaks for unsupported tickers (e.g. some indices/futures).
        if FMP_API_KEY and global_ticker:
            try:
                _sidebar_profile = cached_company_profile(global_ticker, FMP_API_KEY)
            except Exception:
                _sidebar_profile = None
            if _sidebar_profile is not None:
                _name = getattr(_sidebar_profile, "name", None) or global_ticker
                _sector = getattr(_sidebar_profile, "sector", None) or ""
                _industry = getattr(_sidebar_profile, "industry", None) or ""
                _desc = getattr(_sidebar_profile, "description_en", None) or ""

                st.markdown(f"**{_name}**")
                if _sector or _industry:
                    sector_line = " · ".join([x for x in [_sector, _industry] if x])
                    st.caption(sector_line)
                if _desc:
                    # Trim to ~240 chars and end at last full sentence/word.
                    _MAX = 240
                    if len(_desc) > _MAX:
                        _cut = _desc[:_MAX]
                        # backtrack to last sentence end or whitespace for clean break
                        _stop = max(_cut.rfind(". "), _cut.rfind("? "), _cut.rfind("! "))
                        if _stop < 120:
                            _stop = _cut.rfind(" ")
                        _desc_short = (_cut[:_stop + 1] if _stop > 0 else _cut) + "…"
                    else:
                        _desc_short = _desc
                    st.caption(_desc_short)

    # ── Densities section (hero banner + chart + heatmap toggle + skew + math) ──
    try:
        render_densidades(global_ticker)
    except Exception as e:
        st.error(f"Error rendering Densities: {e}")
        import traceback
        st.code(traceback.format_exc())

    # ── Company section (logo + facts + AI description), inlined below chart ──
    st.divider()
    try:
        render_empresa(global_ticker)
    except Exception as e:
        st.error(f"Error rendering Company section: {e}")

    # Pie del sidebar (al final, después de toda la página principal).
    with st.sidebar:
        st.divider()
        st.caption("Data: FMP · tastytrade · Anthropic Claude")
        # Marcador de build: en Render muestra el SHA desplegado (RENDER_GIT_COMMIT),
        # en local muestra "local". Sirve para verificar qué commit está vivo.
        _build = os.getenv("RENDER_GIT_COMMIT", "")[:7] or "local"
        st.caption(f"build · {_build}")


if __name__ == "__main__":
    main()
