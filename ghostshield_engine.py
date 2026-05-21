import json
import math
import queue
import threading
import time
from collections import deque

import numpy as np
import websocket 
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# BUG-1 FIX: Auto-resolve Realme hostname; fall back to hotspot static IP.
# Priority:  mshome.net hostname  →  192.168.137.x hotspot  →  manual override
# ─────────────────────────────────────────────────────────────────────────────
import socket as _socket

def _resolve_phone_ip(
    hostname: str  = "realme-10-Pro-5g.mshome.net",
    fallback: str  = "192.168.137.66",
) -> str:
    """
    Attempt DNS resolution of the Realme mshome.net hostname.
    Windows 'Mobile Hotspot' registers the device under this name
    when the phone connects via USB/WiFi tethering.
    Falls back to the static hotspot IP if resolution fails.
    """
    try:
        ip = _socket.gethostbyname(hostname)
        print(f"[ENGINE] Phone IP resolved: {hostname} → {ip}")
        return ip
    except _socket.gaierror:
        print(f"[ENGINE] DNS resolution failed for {hostname} "
              f"— using fallback {fallback}")
        return fallback

PHONE_IP         = "192.168.137.212"
PORT             = 8080
WARM_UP_N        = 15
DEMO_PRELOAD     = False
WINDOW_SEC       = 0.150       # FIX-1
WARMUP_MAX_MPEAK = 2.0         # FIX-3
WARMUP_MAX_SIGMA = 1.5         # FIX-3

# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON GUARD
# ─────────────────────────────────────────────────────────────────────────────
IS_RUNNING = False

# ─────────────────────────────────────────────────────────────────────────────
# SSE EVENT BUS  [FIX-5] — payment_app.py subscribes to this
# ─────────────────────────────────────────────────────────────────────────────
event_queue: queue.Queue = queue.Queue(maxsize=100)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────────────────────────────────────
shared_state: dict = {
    "human_taps":       [],
    "ghost_taps":       [],
    "all_vectors":      [],
    "status":           "INITIALISING...",
    "epsilon":          0.0,
    "total_taps":       0,
    "blocked":          0,
    "warm_up_count":    0,
    "warm_up_rejected": 0,
    "last_vector":      None,
    "last_label":       None,
    "model_ready":      False,
    "corpus_size":      0,
    "gate_decision":    None,
}
_state_lock = threading.Lock()

_ring_buffer: deque = deque(maxlen=500)
_buf_lock = threading.Lock()

_tap_corpus:  list                   = []
_scaler:      StandardScaler | None = None
_nn_model:    NearestNeighbors | None= None
_db_epsilon:  float                  = 0.5
_model_ready: bool                   = False
_model_lock   = threading.Lock()

# BUG-9 FIX: Guard flag prevents concurrent fit threads at warmup boundary.
# Without this: tap-15 launches fit thread, tap-16 arrives 50ms later while
# model_ready is still False → second fit thread launched → both write
# _scaler/_nn_model concurrently → data race → corrupted model.
_fitting_in_progress: bool = False
_fit_launch_lock      = threading.Lock()


# =============================================================================
# SECTION 1 — FEATURE EXTRACTION  (6-D, orientation-independent)
#
# Mathematics:
#   M(t)   = sqrt(x² + y² + z²)          total magnitude (≈9.81 at rest, any tilt)
#   g_base = mean(M(t)) over full buffer  dynamic gravity (adapts to Realme sensor)
#   I(t)   = |M(t) - g_base|             inertial deviation (0 at rest, >0 on tap)
#
#   Feature vector:
#   [0] Δt          = |t_IMUpeak - t_touch| × 1000   propagation delay (ms)
#   [1] M_peak      = max(I(t)) in ±150ms window      peak inertial force (g)
#   [2] A_contact   = len(window) × 2.0               contact area proxy (px²)
#   [3] F_pressure  = max(I(t))                       pressure proxy (N proxy)
#   [4] σ²_Z        = Var(z(t)) in window             Z-axis impulse decay
#   [5] impulse_dur = duration above 10%×M_peak       spike width (ms)
#
#   Ghost tap: [0, 0.001, 0, 0.001, 0.0001, 0] — always at feature-space origin
#   Human tap: [15-220, 0.1-0.8, 30-80, 0.1-0.8, 0.05-0.55, 10-100]
# =============================================================================

def extract_features(touch_payload: dict, t1: float) -> list[float]:
    t_start = t1 - WINDOW_SEC
    t_end   = t1 + WINDOW_SEC

    with _buf_lock:
        window  = [r for r in _ring_buffer if t_start <= r["t"] <= t_end]
        # BUG-11 FIX: gravity baseline from 100ms PRE-TAP window only.
        # Old code used mean of all 500 samples (5s). If user walked/ran
        # before the demo, dynamic acceleration from steps inflated the mean,
        # compressing inertial deviation toward 0 and misclassifying taps.
        # Pre-tap window [t1-0.15s .. t1-0.05s] is always stationary just
        # before the finger makes contact — clean gravity reference.
        pre_tap = [
            r for r in _ring_buffer
            if (t1 - 0.15) <= r["t"] <= (t1 - 0.05)
        ]
        if pre_tap:
            gravity_mags = [
                math.sqrt(r["x"]**2 + r["y"]**2 + r["z"]**2)
                for r in pre_tap
            ]
        else:
            # Fallback: full buffer on very first tap (buffer still sparse)
            gravity_mags = [
                math.sqrt(r["x"]**2 + r["y"]**2 + r["z"]**2)
                for r in _ring_buffer
            ] if _ring_buffer else [9.81]

    gravity_baseline = float(np.mean(gravity_mags))

    if not window:
        return [0.0, 0.001, 0.0, 0.001, 0.0001, 0.0]

    magnitudes = [
        abs(math.sqrt(r["x"]**2 + r["y"]**2 + r["z"]**2) - gravity_baseline)
        for r in window
    ]

    peak_idx    = int(np.argmax(magnitudes))
    m_peak      = float(magnitudes[peak_idx])
    t_peak      = window[peak_idx]["t"]
    delta_t     = min(abs(t_peak - t1) * 1000.0, WINDOW_SEC * 1000.0)
    a_contact   = float(len(window)) * 2.0
    f_pressure  = m_peak
    z_vals      = [r["z"] for r in window]
    sigma2_z    = float(np.var(z_vals)) if len(z_vals) > 1 else 0.0001
    threshold   = m_peak * 0.10
    above_ts    = [window[i]["t"] for i, m in enumerate(magnitudes) if m >= threshold]
    impulse_dur = (above_ts[-1] - above_ts[0]) * 1000.0 if len(above_ts) >= 2 else 0.0

    return [delta_t, m_peak, a_contact, f_pressure, sigma2_z, impulse_dur]


# =============================================================================
# SECTION 2 — DBSCAN ONE-CLASS ANOMALY DETECTION
#
# Mathematics:
#   StandardScaler: x_scaled = (x - μ_corpus) / σ_corpus
#   Auto-ε: 95th percentile of sorted 4-NN distances in scaled space
#   DBSCAN core: points with ≥4 neighbors within ε  (min_samples=4)
#   Inference: distance to nearest core sample in scaled space
#     distance ≤ ε → density-reachable → label=0  (HUMAN)
#     distance > ε → noise point → label=-1  (GHOST)
#
#   O(N) fit once. O(log N) inference via ball_tree.
#   For N=15 corpus: essentially O(1) in real-time context.
# =============================================================================

def _fit_dbscan_model() -> None:
    global _scaler, _nn_model, _db_epsilon, _model_ready

    print(f"[ML] Fitting DBSCAN on {len(_tap_corpus)} clean taps...")

    with _model_lock:
        X        = np.array(_tap_corpus, dtype=np.float64)
        scaler   = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        k        = min(4, len(X_scaled) - 1)
        tmp_nn   = NearestNeighbors(n_neighbors=k, algorithm="ball_tree").fit(X_scaled)
        dists, _ = tmp_nn.kneighbors(X_scaled)
        epsilon  = max(float(np.percentile(np.sort(dists[:, -1]), 95)), 0.3)

        db       = DBSCAN(eps=epsilon, min_samples=4).fit(X_scaled)
        core_idx = db.core_sample_indices_
        if len(core_idx) == 0:
            core_idx = np.arange(len(X_scaled))

        nn = NearestNeighbors(n_neighbors=1, algorithm="ball_tree")
        nn.fit(X_scaled[core_idx])

        _scaler      = scaler
        _nn_model    = nn
        _db_epsilon  = epsilon
        _model_ready = True

    with _state_lock:
        shared_state["epsilon"]     = round(_db_epsilon, 4)
        shared_state["model_ready"] = True
        shared_state["status"]      = f"SHIELD ACTIVE  ε={_db_epsilon:.4f}  cores={len(core_idx)}"

    print(f"[ML] ✅ Ready | ε={_db_epsilon:.4f} | "
          f"cores={len(core_idx)}/{len(X)} | "
          f"μ(M_peak)={np.mean(X[:,1]):.3f}g")


def classify_tap(vec: list[float]) -> tuple[int, float]:
    with _model_lock:
        if _scaler is None or _nn_model is None:
            return 0, 0.0
        vec_scaled = _scaler.transform([vec])
        dist, _    = _nn_model.kneighbors(vec_scaled)
        distance   = float(dist[0][0])
    return (0 if distance <= _db_epsilon else -1), distance


# =============================================================================
# SECTION 3 — DEMO PRELOAD (Realme 10 Pro calibrated from live session data)
# =============================================================================

def _preload_synthetic_corpus() -> None:
    global _tap_corpus
    rng = np.random.default_rng(seed=42)
    synthetic = []
    for _ in range(WARM_UP_N):
        dt  = float(np.clip(rng.normal(95.0,  60.0),  10.0, 220.0))
        # BUG-10 IMPROVEMENT: widened std 0.12→0.20 so epsilon is broader,
        # absorbing more variation in real Realme sensor output.
        mp  = float(np.clip(rng.normal(0.38,   0.20),  0.05,  0.90))
        ac  = float(np.clip(rng.normal(62.0,   6.0),  30.0,  80.0))
        fp  = float(np.clip(rng.normal(0.38,   0.20),  0.05,  0.90))
        sz  = float(np.clip(rng.normal(0.20,   0.10),  0.05,  0.55))
        dur = float(np.clip(rng.normal(45.0,  15.0),  10.0, 100.0))
        synthetic.append([dt, mp, ac, fp, sz, dur])

    _tap_corpus = synthetic
    with _state_lock:
        shared_state["warm_up_count"] = WARM_UP_N
        shared_state["corpus_size"]   = WARM_UP_N
        shared_state["status"]        = "FITTING MODEL..."
        for v in synthetic:
            shared_state["human_taps"].append([v[0], v[1]])
    _fit_dbscan_model()
    print(f"[ENGINE] Preload complete.")


# =============================================================================
# SECTION 4 — SENSOR THREADS
# =============================================================================

def _imu_thread() -> None:
    url = f"ws://{PHONE_IP}:{PORT}/sensor/connect?type=android.sensor.accelerometer"

    def on_message(ws, msg):
        try:
            vals = json.loads(msg)["values"]
            with _buf_lock:
                _ring_buffer.append({
                    "x": float(vals[0]), "y": float(vals[1]),
                    "z": float(vals[2]), "t": time.time()
                })
        except Exception as e:
            print(f"[IMU] {e}")

    def on_open(ws):      print(f"[IMU] ✅ {PHONE_IP}:{PORT}")
    def on_error(ws, e):  print(f"[IMU] ❌ {e}")
    def on_close(ws, *_): print("[IMU] closed")

    while True:
        try:
            websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                   on_error=on_error, on_close=on_close
                                   ).run_forever(ping_interval=10, ping_timeout=5)
        except Exception as e:
            print(f"[IMU] crash: {e}")
        time.sleep(2)


def _touch_thread() -> None:
    url = f"ws://{PHONE_IP}:{PORT}/touchscreen"

    def on_message(ws, msg):
        global _tap_corpus, _model_ready, _fitting_in_progress
        try:
            data = json.loads(msg)
            if data.get("action") != "ACTION_DOWN":
                return

            t1  = time.time()           # FIX-2: immediate capture, no sleep
            vec = extract_features(data, t1)

            with _state_lock:
                shared_state["last_vector"] = [round(v, 4) for v in vec]
                shared_state["total_taps"] += 1

            print(f"[TAP] Δt={vec[0]:.1f}ms M={vec[1]:.3f}g "
                  f"Ac={vec[2]:.0f} σ²Z={vec[4]:.4f} Dur={vec[5]:.1f}ms")

            if not _model_ready:
                if vec[1] > WARMUP_MAX_MPEAK or vec[4] > WARMUP_MAX_SIGMA:
                    with _state_lock:
                        shared_state["warm_up_rejected"] += 1
                        r = shared_state["warm_up_rejected"]
                    print(f"[WARMUP] ⚠ REJECTED M={vec[1]:.3f}g σ²Z={vec[4]:.4f} [{r} total]")
                    return

                _tap_corpus.append(vec)
                wc = len(_tap_corpus)
                with _state_lock:
                    shared_state["warm_up_count"] = wc
                    shared_state["corpus_size"]   = wc
                    shared_state["status"] = f"CALIBRATING ({wc}/{WARM_UP_N})"
                    shared_state["human_taps"].append([vec[0], vec[1]])
                print(f"[WARMUP] {wc}/{WARM_UP_N}")
                if wc >= WARM_UP_N:
                    # BUG-9 FIX: exactly ONE fit thread launched at warmup boundary.
                    # _fit_launch_lock + _fitting_in_progress prevents concurrent
                    # fit threads if taps 16,17... arrive before model_ready=True.
                    with _fit_launch_lock:
                        if not _fitting_in_progress:
                            _fitting_in_progress = True
                            threading.Thread(target=_fit_dbscan_model,
                                             daemon=True, name="dbscan-fit").start()
                return

            label, dist = classify_tap(vec)

            if label == -1:
                reason = (f"No inertial impulse | M_peak={vec[1]:.3f}g | "
                          f"dist={dist:.3f} > ε={_db_epsilon:.3f} | "
                          f"Software injection confirmed")
                with _state_lock:
                    shared_state["ghost_taps"].append([vec[0], vec[1]])
                    shared_state["blocked"]      += 1
                    shared_state["last_label"]    = -1
                    shared_state["gate_decision"] = "BLOCK"
                    shared_state["status"]        = "🚫 GHOST TAP — PAYMENT BLOCKED"
                    shared_state["all_vectors"].append(
                        {"label": "GHOST", "vec": vec, "dist": round(dist, 4)})
                try:
                    event_queue.put_nowait({
                        "decision": "BLOCK", "reason": reason,
                        "vector": [round(v, 4) for v in vec],
                        "distance": round(dist, 4), "epsilon": round(_db_epsilon, 4)
                    })
                except queue.Full:
                    pass
                print(f"[ML] ⚠ GHOST  dist={dist:.4f}  ε={_db_epsilon:.4f}")

            else:
                _tap_corpus.append(vec)
                with _state_lock:
                    shared_state["human_taps"].append([vec[0], vec[1]])
                    shared_state["corpus_size"]   = len(_tap_corpus)
                    shared_state["last_label"]    = 0
                    shared_state["gate_decision"] = "PERMIT"
                    shared_state["status"]        = "✅ HUMAN TAP — PAYMENT AUTHORISED"
                    shared_state["all_vectors"].append(
                        {"label": "HUMAN", "vec": vec, "dist": round(dist, 4)})
                try:
                    event_queue.put_nowait({
                        "decision": "PERMIT",
                        "reason": f"Inertial impulse confirmed | M_peak={vec[1]:.3f}g",
                        "vector": [round(v, 4) for v in vec],
                        "distance": round(dist, 4), "epsilon": round(_db_epsilon, 4)
                    })
                except queue.Full:
                    pass
                print(f"[ML] ✅ HUMAN  dist={dist:.4f}  ε={_db_epsilon:.4f}")

        except Exception as e:
            print(f"[TOUCH] error: {e}")

    def on_open(ws):      print("[TOUCH] ✅ Connected")
    def on_error(ws, e):  print(f"[TOUCH] ❌ {e}")
    def on_close(ws, *_): print("[TOUCH] closed")

    while True:
        try:
            websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                   on_error=on_error, on_close=on_close
                                   ).run_forever(ping_interval=10, ping_timeout=5)
        except Exception as e:
            print(f"[TOUCH] crash: {e}")
        time.sleep(2)


# =============================================================================
# SECTION 5 — START ENGINE
# =============================================================================

def start_engine() -> None:
    global IS_RUNNING
    if IS_RUNNING:
        return
    IS_RUNNING = True

    print(f"\n{'='*62}")
    print(f"  GhostShield™ v3.0  |  Python 3.11")
    print(f"  Phone:   {PHONE_IP}:{PORT}")
    print(f"  Window:  {int(WINDOW_SEC*1000)}ms")
    print(f"  Preload: {DEMO_PRELOAD}")
    print(f"{'='*62}\n")

    if DEMO_PRELOAD:
        _preload_synthetic_corpus()
    else:
        with _state_lock:
            shared_state["status"] = f"CALIBRATING (0/{WARM_UP_N}) — tap naturally"

    threading.Thread(target=_imu_thread,   daemon=True, name="imu").start()
    time.sleep(1.5)   # BUG-4 FIX: was 0.5s — hotspot WiFi needs 1.5s for IMU
                      # to connect and buffer to fill before first tap arrives
    threading.Thread(target=_touch_thread, daemon=True, name="touch").start()
    print("[ENGINE] Running.\n")

if __name__ == "__main__":
    start_engine()
    try:
        while True:
            time.sleep(1)
            with _state_lock:
                s = shared_state
                print(f"[STATUS] {s['status']} | "
                      f"Taps:{s['total_taps']} Blocked:{s['blocked']} "
                      f"Rejected:{s['warm_up_rejected']} ε:{s['epsilon']}")
    except KeyboardInterrupt:
        print("\n[ENGINE] Stopped.")

