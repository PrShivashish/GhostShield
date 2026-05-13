# =============================================================================
# dashboard.py  —  GhostShield™  v3.0
# Streamlit Projector Dashboard  |  Senior ML Director Architecture
#
# Run:  streamlit run dashboard.py
#       (in a SEPARATE terminal AFTER python payment_app.py is running)
#
# BUG-3 FIX: dashboard.py and payment_app.py run as SEPARATE OS processes.
#   Python in-process dicts (shared_state) are NOT shared across processes.
#   WRONG (old): import ghostshield_engine → starts duplicate engine instance
#   CORRECT:     poll http://localhost:5000/status every 0.5s via requests
#
# The engine lives ONLY inside payment_app.py's process.
# dashboard.py is a pure read-only HTTP consumer.
# =============================================================================

import time

import numpy as np
import plotly.graph_objects as go
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG — must be first Streamlit command
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GhostShield™ — Live",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# BUG-3 FIX: HTTP state fetch from payment_app.py
# dashboard.py polls http://localhost:5000/status
# payment_app.py owns the engine and shared_state
# ─────────────────────────────────────────────────────────────────────────────
PAYMENT_APP_URL = "http://localhost:5000"
WARM_UP_N       = 15   # must match engine config

_EMPTY_STATE = {
    "status":           "Waiting for payment_app.py...",
    "model_ready":      False,
    "warm_up_count":    0,
    "warm_up_rejected": 0,
    "total_taps":       0,
    "blocked":          0,
    "epsilon":          0.0,
    "corpus_size":      0,
    "last_vector":      None,
    "last_label":       None,
    "human_taps":       [],
    "ghost_taps":       [],
    "all_vectors":      [],
}

def _fetch_state() -> dict:
    """
    Fetch current engine state from payment_app.py /status endpoint.
    Returns _EMPTY_STATE on any connection error (payment_app not started yet).
    """
    try:
        r = requests.get(f"{PAYMENT_APP_URL}/status", timeout=1.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return dict(_EMPTY_STATE)

# ─────────────────────────────────────────────────────────────────────────────
# CSS — OLED dark, premium typography, pulsing alerts
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', system-ui, sans-serif;
    background: #0A0A0A;
    color: #E5E5E5;
}
.stApp                          { background: #0A0A0A; }
section[data-testid="stSidebar"]{ background: #0D0D0D; border-right: 1px solid #1A1A1A; }

/* ── Header ──────────────────────────────────────────────────────────── */
.gs-header {
    background: linear-gradient(110deg, #0F0F1A 0%, #0A0A14 100%);
    border: 1px solid #1E1E2E;
    border-left: 3px solid #6C63FF;
    border-radius: 10px;
    padding: 18px 24px 14px;
    margin-bottom: 16px;
}
.gs-header h1 {
    font-size: 1.9em; font-weight: 700; color: #8B84FF;
    margin: 0 0 4px; letter-spacing: 1.5px; text-transform: uppercase;
}
.gs-header p {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72em; color: #444; margin: 0; letter-spacing: 1px;
}

/* ── Alert banners ───────────────────────────────────────────────────── */
@keyframes pulse {
    0%,100% { opacity: 1;   box-shadow: 0 0 15px rgba(255,59,48,0.4); }
    50%      { opacity: 0.7; box-shadow: 0 0 45px rgba(255,59,48,0.8); }
}
.banner-blocked {
    background: linear-gradient(110deg, #1A0800, #2A0A00);
    border: 1px solid rgba(255,59,48,0.4);
    border-radius: 10px; padding: 18px 24px;
    text-align: center;
    font-family: 'Inter', sans-serif;
    font-size: 1.5em; font-weight: 700;
    color: #FF5B50; letter-spacing: 2px; text-transform: uppercase;
    animation: pulse 1.1s ease-in-out infinite;
}
.banner-auth {
    background: linear-gradient(110deg, #001A0A, #002010);
    border: 1px solid rgba(0,212,106,0.3);
    border-radius: 10px; padding: 18px 24px;
    text-align: center;
    font-family: 'Inter', sans-serif;
    font-size: 1.4em; font-weight: 700;
    color: #00D46A; letter-spacing: 2px; text-transform: uppercase;
}
.banner-warmup {
    background: linear-gradient(110deg, #12100A, #1A1500);
    border: 1px solid rgba(255,184,0,0.25);
    border-radius: 10px; padding: 16px 24px;
    text-align: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.0em; color: #FFB800; letter-spacing: 1px;
}
.banner-ready {
    background: linear-gradient(110deg, #0A0A18, #0D0D22);
    border: 1px solid rgba(108,99,255,0.25);
    border-radius: 10px; padding: 14px 24px;
    text-align: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95em; color: #6C63FF; letter-spacing: 1px;
}

/* ── Metrics ─────────────────────────────────────────────────────────── */
div[data-testid="metric-container"] {
    background: #111; border: 1px solid #1A1A1A;
    border-radius: 8px; padding: 14px 16px;
}
div[data-testid="metric-container"] label {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.65em !important; color: #444 !important;
    letter-spacing: 1.8px; text-transform: uppercase;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.9em !important; font-weight: 700 !important;
    color: #E5E5E5 !important;
}

/* ── Tap history rows ─────────────────────────────────────────────────── */
.vec-human {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78em; color: #00D46A; padding: 3px 0;
    border-bottom: 1px solid rgba(0,212,106,0.06);
}
.vec-ghost {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78em; color: #FF5B50; padding: 3px 0;
    border-bottom: 1px solid rgba(255,59,48,0.06);
}

/* ── Sidebar section labels ───────────────────────────────────────────── */
.sb-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65em; color: #333;
    letter-spacing: 2px; text-transform: uppercase;
    padding-bottom: 5px;
    border-bottom: 1px solid #1A1A1A;
    margin: 14px 0 6px;
}

/* ── Physics invariant box ───────────────────────────────────────────── */
.physics-box {
    background: #0D0D1A;
    border: 1px solid #1E1E35;
    border-left: 2px solid #6C63FF;
    border-radius: 6px;
    padding: 10px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72em;
    color: #666;
    line-height: 1.8;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="gs-header">
  <h1>🛡️ GhostShield™  v3.0</h1>
  <p>
    REAL-TIME INERTIAL-CAPACITIVE PAYMENT FRAUD PREVENTION &nbsp;·&nbsp;
    F = m × a &nbsp;·&nbsp; DBSCAN ONE-CLASS ANOMALY DETECTION &nbsp;·&nbsp;
    ORIENTATION-INDEPENDENT FEATURES &nbsp;·&nbsp; LPU PATENT PROTOTYPE
  </p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🛡️ GhostShield")
    refresh = st.slider("Refresh interval (s)", 0.3, 2.0, 0.5, 0.1)

    st.markdown('<div class="sb-label">Physics Invariant</div>', unsafe_allow_html=True)
    st.markdown("""
<div class="physics-box">
F = m × a<br>
Physical tap → IMU spike → M_peak > 0<br>
ADB inject → no force → M_peak ≈ 0<br>
<br>
Ghost ≡ (0, 0) in feature space<br>
Human ≡ M_peak > 0.1g  always<br>
<br>
Orientation does NOT matter:<br>
||gravity||₂ = 9.81g at any tilt
</div>
""", unsafe_allow_html=True)

    st.markdown('<div class="sb-label">6-D Feature Space</div>', unsafe_allow_html=True)
    st.markdown("""
| # | Symbol | Ghost | Human |
|---|--------|-------|-------|
| 0 | Δt (ms) | ≈ 0 | 10–220 |
| 1 | M_peak (g) | ≈ 0.001 | 0.1–0.8 |
| 2 | A_contact | 0 | 30–80 |
| 3 | F_pressure | 0.001 | 0.1–0.8 |
| 4 | σ²_Z | ≈ 0 | 0.05–0.55 |
| 5 | Dur (ms) | ≈ 0 | 10–100 |
""")

    st.markdown('<div class="sb-label">DBSCAN Mathematics</div>', unsafe_allow_html=True)
    st.markdown("""
<div class="physics-box">
StandardScaler: (x-μ)/σ<br>
ε = P95(4-NN distances)<br>
Core: ≥4 neighbors within ε<br>
Inference: dist(new, core) vs ε<br>
O(log N) per tap via ball_tree
</div>
""", unsafe_allow_html=True)

    st.markdown('<div class="sb-label">Attack Coverage</div>', unsafe_allow_html=True)
    for a in [
        "✅ ADB shell input tap",
        "✅ MotionEvent injection",
        "✅ Accessibility RAT",
        "✅ GhostTouch EMI",
        "✅ USB WIGHT injection",
        "✅ Windows Phone Link",
        "✅ Vysor / scrcpy remote",
        "✅ Vibrator + ADB combo",
    ]:
        st.markdown(
            f"<small style='font-family:JetBrains Mono;color:#333;font-size:0.78em'>{a}</small>",
            unsafe_allow_html=True
        )

    st.markdown('<div class="sb-label">Demo Run Order</div>', unsafe_allow_html=True)
    st.markdown(
        "<div style='font-family:JetBrains Mono;color:#444;font-size:0.72em;"
        "line-height:1.9;padding:8px 10px;background:#0D0D0D;"
        "border:1px solid #1A1A1A;border-radius:6px'>"
        "<span style='color:#6C63FF'>Terminal 1:</span><br>"
        "&nbsp;&nbsp;python payment_app.py<br>"
        "<span style='color:#6C63FF'>Phone:</span><br>"
        "&nbsp;&nbsp;http://LAPTOP_IP:5000<br>"
        "<span style='color:#6C63FF'>Terminal 2:</span><br>"
        "&nbsp;&nbsp;streamlit run dashboard.py<br>"
        "<span style='color:#6C63FF'>Terminal 3 (demo):</span><br>"
        "&nbsp;&nbsp;python ghost_injector.py<br>"
        "<span style='color:#444;font-size:0.9em'>⚠ Start payment_app.py FIRST<br>"
        "dashboard polls localhost:5000</span>"
        "</div>",
        unsafe_allow_html=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# LIVE SLOT CONTAINERS
# ─────────────────────────────────────────────────────────────────────────────
slot_banner  = st.empty()
slot_metrics = st.empty()
slot_chart   = st.empty()
slot_vector  = st.empty()
slot_history = st.empty()

# ─────────────────────────────────────────────────────────────────────────────
# LIVE LOOP
# ─────────────────────────────────────────────────────────────────────────────
while True:

    # HTTP fetch from payment_app.py  [BUG-3 FIX]
    s = _fetch_state()

    status      = s.get("status",           _EMPTY_STATE["status"])
    human_taps  = s.get("human_taps",       [])
    ghost_taps  = s.get("ghost_taps",       [])
    total       = s.get("total_taps",       0)
    blocked     = s.get("blocked",          0)
    epsilon     = s.get("epsilon",          0.0)
    warm_count  = s.get("warm_up_count",    0)
    rejected    = s.get("warm_up_rejected", 0)
    model_ready = s.get("model_ready",      False)
    last_vec    = s.get("last_vector",      None)
    last_label  = s.get("last_label",       None)
    corpus_size = s.get("corpus_size",      0)
    all_vectors = s.get("all_vectors",      [])[-25:]

    # ── BANNER ────────────────────────────────────────────────────────────
    with slot_banner.container():
        if "GHOST" in status or "BLOCKED" in status:
            st.markdown(
                f'<div class="banner-blocked">⚠ &nbsp; {status}</div>',
                unsafe_allow_html=True
            )
        elif "HUMAN" in status or "AUTHORISED" in status:
            st.markdown(
                f'<div class="banner-auth">✓ &nbsp; {status}</div>',
                unsafe_allow_html=True
            )
        elif "CALIBRAT" in status or "WARMING" in status:
            pct = int(min(100, (warm_count / max(WARM_UP_N, 1)) * 100))
            st.markdown(
                f'<div class="banner-warmup">'
                f'⏳ &nbsp; {status} &nbsp;·&nbsp; {pct}% '
                f'&nbsp;·&nbsp; Rejected: {rejected}'
                f'</div>',
                unsafe_allow_html=True
            )
            st.progress(pct)
        else:
            st.markdown(
                f'<div class="banner-ready">◈ &nbsp; {status}</div>',
                unsafe_allow_html=True
            )

    # ── METRICS ───────────────────────────────────────────────────────────
    with slot_metrics.container():
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("TOTAL TAPS",   total)
        c2.metric("BLOCKED",      blocked,
                  delta=f"+{blocked}" if blocked > 0 else None,
                  delta_color="inverse")
        c3.metric("AUTHORISED",   total - blocked)
        c4.metric("DBSCAN ε",     f"{epsilon:.4f}" if epsilon else "—")
        c5.metric("CORPUS",       corpus_size)
        c6.metric("REJECTED",     rejected)
        c7.metric("MODEL",
                  "LIVE ✅" if model_ready else f"{warm_count}/{WARM_UP_N}")

    # ── SCATTER CHART ─────────────────────────────────────────────────────
    with slot_chart.container():
        fig = go.Figure()

        # ── Human cluster (green dots)
        if human_taps:
            hx = [v[0] for v in human_taps]
            hy = [v[1] for v in human_taps]
            fig.add_trace(go.Scatter(
                x=hx, y=hy,
                mode="markers",
                name="Human Biological Tap",
                marker=dict(
                    color="rgba(0, 212, 106, 0.80)",
                    size=12,
                    symbol="circle",
                    line=dict(color="rgba(0,255,130,0.9)", width=1.0),
                ),
                hovertemplate=(
                    "<b>✓ Human Tap</b><br>"
                    "Δt = %{x:.1f} ms<br>"
                    "M_peak = %{y:.3f} g"
                    "<extra></extra>"
                ),
            ))

        # ── Ghost taps (red X — should always cluster at origin)
        if ghost_taps:
            gx = [v[0] for v in ghost_taps]
            gy = [v[1] for v in ghost_taps]
            fig.add_trace(go.Scatter(
                x=gx, y=gy,
                mode="markers",
                name="⚠ Ghost Tap — BLOCKED",
                marker=dict(
                    color="rgba(255, 59, 48, 0.95)",
                    size=20,
                    symbol="x",
                    line=dict(color="rgba(255,59,48,1)", width=3),
                ),
                hovertemplate=(
                    "<b>⚠ GHOST TAP</b><br>"
                    "Δt = %{x:.1f} ms<br>"
                    "M_peak = %{y:.3f} g<br>"
                    "label = -1 (noise point)"
                    "<extra></extra>"
                ),
            ))

        # ── Epsilon boundary circle (visual only, drawn in scaled-space proxy)
        if model_ready and epsilon > 0 and len(human_taps) >= 3:
            cx = float(np.mean([v[0] for v in human_taps]))
            cy = float(np.mean([v[1] for v in human_taps]))
            std_x = max(float(np.std([v[0] for v in human_taps])), 1.0)
            std_y = max(float(np.std([v[1] for v in human_taps])), 0.01)
            theta = np.linspace(0, 2 * np.pi, 150)
            # epsilon is in scaled space; back-project to data space for visual
            rx = epsilon * std_x
            ry = epsilon * std_y
            fig.add_trace(go.Scatter(
                x=cx + rx * np.cos(theta),
                y=cy + ry * np.sin(theta),
                mode="lines",
                name=f"ε-boundary ({epsilon:.4f})",
                line=dict(color="rgba(108,99,255,0.35)", width=1.5, dash="dot"),
                hoverinfo="skip",
            ))

        # ── Annotations
        fig.add_annotation(
            x=4, y=0.04,
            text="⚠ Ghost Zone<br>Δt≈0ms · M≈0g<br>ADB/RAT/Remote",
            showarrow=False,
            font=dict(color="#FF5B50", size=11, family="JetBrains Mono"),
            bgcolor="rgba(60,0,0,0.55)",
            bordercolor="rgba(255,59,48,0.4)",
            borderwidth=1, borderpad=7,
            align="left",
        )
        if len(human_taps) >= 5:
            fig.add_annotation(
                x=float(np.mean([v[0] for v in human_taps])),
                y=float(np.max([v[1] for v in human_taps])) + 0.08,
                text="✓ Biological Cluster<br>Physical touch confirmed",
                showarrow=False,
                font=dict(color="#00D46A", size=11, family="JetBrains Mono"),
                bgcolor="rgba(0,40,20,0.6)",
                bordercolor="rgba(0,212,106,0.3)",
                borderwidth=1, borderpad=7,
                align="center",
            )

        # ── Layout
        fig.update_layout(
            title=dict(
                text=(
                    "GhostShield™  ·  DBSCAN Feature Space  ·  "
                    "Δt (ms) vs M_peak (g)  ·  "
                    "Ghost = (0,0)  ·  Human = Cluster"
                ),
                font=dict(size=14, color="#555", family="JetBrains Mono"),
                x=0.5,
            ),
            xaxis=dict(
                title=dict(
                    text="Temporal Delta Δt  (milliseconds from touch to IMU peak)",
                    font=dict(size=11, color="#444", family="JetBrains Mono"),
                ),
                range=[-8, 260],
                gridcolor="#141414",
                color="#333",
                zeroline=True, zerolinecolor="#2A0A0A", zerolinewidth=2,
                tickfont=dict(family="JetBrains Mono", size=10, color="#444"),
            ),
            yaxis=dict(
                title=dict(
                    text="Peak IMU Inertial Magnitude  M_peak  (g, orientation-independent)",
                    font=dict(size=11, color="#444", family="JetBrains Mono"),
                ),
                range=[-0.04, 2.0],   # BUG-5 FIX: was 1.0, clips taps above 1g
                gridcolor="#141414",
                color="#333",
                zeroline=True, zerolinecolor="#2A0A0A", zerolinewidth=2,
                tickfont=dict(family="JetBrains Mono", size=10, color="#444"),
            ),
            paper_bgcolor="#0A0A0A",
            plot_bgcolor="#0D0D0D",
            legend=dict(
                bgcolor="#111",
                bordercolor="#1A1A1A",
                borderwidth=1,
                font=dict(color="#666", family="JetBrains Mono", size=11),
            ),
            height=500,
            margin=dict(l=70, r=30, t=50, b=70),
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            key="dbscan_scatter",          # BUG-12 FIX: prevents DOM rebuild
            config={                        # BUG-12 FIX: removes toolbar flash
                "displayModeBar":  False,
                "staticPlot":      False,
                "scrollZoom":      False,
                "doubleClick":     False,
                "showTips":        False,
            },
        )

    # ── LAST FEATURE VECTOR ───────────────────────────────────────────────
    with slot_vector.container():
        if last_vec and len(last_vec) >= 6:
            lc = "#FF5B50" if last_label == -1 else "#00D46A"
            lt = "GHOST  label=-1  (noise point outside ε-boundary)" \
                 if last_label == -1 else \
                 "HUMAN  label=0   (density-reachable from core cluster)"
            st.markdown(
                f"<div style='font-family:JetBrains Mono;font-size:0.70em;"
                f"color:#444;letter-spacing:1.5px;text-transform:uppercase;"
                f"margin-bottom:6px'>"
                f"LAST FEATURE VECTOR &nbsp;·&nbsp; "
                f"<span style='color:{lc};font-weight:600'>{lt}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            v = last_vec
            vc = st.columns(6)
            labels_units = [
                ("Δt (ms)",    f"{v[0]:.1f}"),
                ("M_peak (g)", f"{v[1]:.4f}"),
                ("A_contact",  f"{v[2]:.0f}"),
                ("F_pressure", f"{v[3]:.4f}"),
                ("σ²_Z",       f"{v[4]:.4f}"),
                ("Dur (ms)",   f"{v[5]:.1f}"),
            ]
            for col, (lbl, val) in zip(vc, labels_units):
                col.metric(lbl, val)

    # ── TAP HISTORY TABLE ─────────────────────────────────────────────────
    with slot_history.container():
        if all_vectors:
            st.markdown(
                "<div style='font-family:JetBrains Mono;font-size:0.65em;"
                "color:#333;letter-spacing:2px;text-transform:uppercase;"
                "margin-bottom:6px'>Tap History (last 25)</div>",
                unsafe_allow_html=True,
            )
            rows_html = ""
            for r in reversed(all_vectors):
                is_ghost = r["label"] == "GHOST"
                cls      = "vec-ghost" if is_ghost else "vec-human"
                icon     = "⚠ GHOST" if is_ghost else "✓ HUMAN"
                v        = r["vec"]
                d        = r.get("dist", "?")
                vec_str  = (
                    f"Δt={v[0]:.1f}ms &nbsp; M={v[1]:.4f}g &nbsp; "
                    f"Ac={v[2]:.0f} &nbsp; Fp={v[3]:.4f} &nbsp; "
                    f"σ²Z={v[4]:.4f} &nbsp; Dur={v[5]:.1f}ms &nbsp; "
                    f"dist={d}"
                ) if len(v) >= 6 else f"Δt={v[0]:.1f}ms M={v[1]:.4f}g"

                rows_html += (
                    f"<div class='{cls}'>"
                    f"<span style='font-weight:600'>{icon}</span>"
                    f" &nbsp;|&nbsp; {vec_str}"
                    f"</div>"
                )
            st.markdown(rows_html, unsafe_allow_html=True)

    time.sleep(refresh)
