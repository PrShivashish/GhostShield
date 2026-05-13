# =============================================================================
# payment_app.py  —  GhostShield™  v3.0
# Flask Payment Server  |  React + Tailwind (CDN, zero build pipeline)
#
# Run:  python payment_app.py
# Then: Open http://LAPTOP_IP:5000 on your phone browser
#       Add to Home Screen → launches as native app (no Chrome UI)
#
# Architecture:
#   GET  /         → serves the React payment UI (single HTML string)
#   GET  /status   → JSON: current engine state (warmup progress, model ready)
#   GET  /events   → SSE stream: pushes PERMIT/BLOCK decisions from engine
#   POST /reset    → resets transaction state for next demo
# =============================================================================

import json
import threading
import time

from flask import Flask, Response, jsonify, request

import ghostshield_engine as engine
from ghostshield_engine import _state_lock, event_queue, shared_state

app = Flask(__name__)

# Start engine once when Flask starts
_engine_start_lock = threading.Lock()


def _ensure_engine():
    with _engine_start_lock:
        if not engine.IS_RUNNING:
            engine.start_engine()


# =============================================================================
# PAYMENT UI HTML — React + Tailwind CDN, zero Node.js
# Psychology: CRED / Apple Pay / premium crypto wallet
# =============================================================================

PAYMENT_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>

  <!-- PWA / Native App Illusion -->
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
  <meta name="apple-mobile-web-app-title" content="GhostShield Pay"/>
  <meta name="mobile-web-app-capable" content="yes"/>
  <meta name="theme-color" content="#0A0A0A"/>
  <title>GhostShield Pay</title>

  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>

  <!-- React 18 CDN (no JSX transform needed with Babel standalone) -->
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            gs: {
              bg:      '#0A0A0A',
              surface: '#111111',
              card:    '#161616',
              border:  '#1F1F1F',
              accent:  '#6C63FF',
              accentlt:'#8B84FF',
              green:   '#00D46A',
              red:     '#FF3B30',
              amber:   '#FFB800',
              text:    '#F5F5F5',
              muted:   '#666666',
              subtle:  '#2A2A2A',
            }
          },
          fontFamily: {
            sans: ['"SF Pro Display"', '"Inter"', 'system-ui', 'sans-serif'],
            mono: ['"SF Mono"', '"Fira Code"', 'monospace'],
          },
          boxShadow: {
            'glow-green': '0 0 30px rgba(0, 212, 106, 0.25)',
            'glow-red':   '0 0 40px rgba(255, 59, 48, 0.35)',
            'glow-accent':'0 0 25px rgba(108, 99, 255, 0.30)',
          },
          backdropBlur: { xs: '2px' },
          animation: {
            'pulse-red':  'pulseRed 1.1s ease-in-out infinite',
            'fade-up':    'fadeUp 0.4s ease-out forwards',
            'scale-in':   'scaleIn 0.35s cubic-bezier(0.34,1.56,0.64,1) forwards',
            'shimmer':    'shimmer 2s linear infinite',
          },
          keyframes: {
            pulseRed: {
              '0%,100%': { boxShadow: '0 0 25px rgba(255,59,48,0.3)', opacity:'1' },
              '50%':     { boxShadow: '0 0 60px rgba(255,59,48,0.7)', opacity:'0.85' },
            },
            fadeUp: {
              from: { opacity:'0', transform:'translateY(20px)' },
              to:   { opacity:'1', transform:'translateY(0)' },
            },
            scaleIn: {
              from: { opacity:'0', transform:'scale(0.85)' },
              to:   { opacity:'1', transform:'scale(1)' },
            },
            shimmer: {
              '0%':   { backgroundPosition: '-200% center' },
              '100%': { backgroundPosition:  '200% center' },
            },
          }
        }
      }
    }
  </script>

  <style>
    * { -webkit-tap-highlight-color: transparent; box-sizing: border-box; }
    body { background: #0A0A0A; overscroll-behavior: none; }

    /* Glassmorphism card */
    .glass {
      background: rgba(255,255,255,0.03);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255,255,255,0.07);
    }

    /* Gradient shimmer text */
    .shimmer-text {
      background: linear-gradient(90deg, #6C63FF 0%, #a29bfe 40%, #6C63FF 80%);
      background-size: 200% auto;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      animation: shimmer 3s linear infinite;
    }

    /* Premium button styles */
    .btn-pay {
      background: linear-gradient(135deg, #6C63FF 0%, #8B84FF 50%, #6C63FF 100%);
      background-size: 200% auto;
      transition: background-position 0.4s ease, transform 0.15s ease, box-shadow 0.3s ease;
      -webkit-tap-highlight-color: transparent;
      touch-action: manipulation;
    }
    .btn-pay:hover  { background-position: right center; box-shadow: 0 0 35px rgba(108,99,255,0.5); }
    .btn-pay:active { transform: scale(0.96); }

    /* Status dots */
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
    .blink { animation: blink 1.5s ease-in-out infinite; }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 0; background: transparent; }

    /* Notch safe area */
    .safe-top    { padding-top: env(safe-area-inset-top, 12px); }
    .safe-bottom { padding-bottom: env(safe-area-inset-bottom, 24px); }
  </style>
</head>
<body class="bg-gs-bg text-gs-text font-sans select-none overflow-hidden">
  <div id="root"></div>

<script type="text/babel">
const { useState, useEffect, useRef, useCallback } = React;

// ── Utility: haptic vibration ─────────────────────────────────────────────
const haptic = (pattern = [10]) => {
  if (navigator.vibrate) navigator.vibrate(pattern);
};

// ── Icons (inline SVG) ────────────────────────────────────────────────────
const ShieldIcon = ({ size = 28, color = '#6C63FF' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M12 2L3 6v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V6L12 2z"
      fill={color} fillOpacity="0.15" stroke={color} strokeWidth="1.5"
      strokeLinejoin="round"/>
    <path d="M9 12l2 2 4-4" stroke={color} strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const LockIcon = ({ size = 18, color = '#666' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <rect x="5" y="11" width="14" height="10" rx="2" stroke={color} strokeWidth="1.5"/>
    <path d="M8 11V7a4 4 0 118 0v4" stroke={color} strokeWidth="1.5"
      strokeLinecap="round"/>
  </svg>
);

const CheckIcon = ({ size = 56 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="10" fill="#00D46A" fillOpacity="0.15" stroke="#00D46A" strokeWidth="1.5"/>
    <path d="M7 12.5l3.5 3.5 6-7" stroke="#00D46A" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const BlockIcon = ({ size = 56 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="10" fill="#FF3B30" fillOpacity="0.15" stroke="#FF3B30" strokeWidth="1.5"/>
    <path d="M15 9l-6 6M9 9l6 6" stroke="#FF3B30" strokeWidth="2.5"
      strokeLinecap="round"/>
  </svg>
);

// ── Status Badge ──────────────────────────────────────────────────────────
const StatusBadge = ({ modelReady, warmupCount, warmupTotal }) => {
  if (modelReady) {
    return (
      <div className="flex items-center gap-2 px-3 py-1 rounded-full"
           style={{background:'rgba(0,212,106,0.1)', border:'1px solid rgba(0,212,106,0.2)'}}>
        <span className="w-2 h-2 rounded-full bg-gs-green blink"/>
        <span className="text-gs-green text-xs font-semibold tracking-widest">SHIELD ACTIVE</span>
      </div>
    );
  }
  const pct = Math.round((warmupCount / warmupTotal) * 100);
  return (
    <div className="flex items-center gap-2 px-3 py-1 rounded-full"
         style={{background:'rgba(255,184,0,0.1)', border:'1px solid rgba(255,184,0,0.2)'}}>
      <span className="w-2 h-2 rounded-full bg-gs-amber blink"/>
      <span className="text-gs-amber text-xs font-semibold tracking-widest">
        CALIBRATING {pct}%
      </span>
    </div>
  );
};

// ── PIN Pad ───────────────────────────────────────────────────────────────
const PinPad = ({ onComplete, onBack }) => {
  const [pin, setPin] = useState([]);
  const PIN_LENGTH = 4;

  const press = (digit) => {
    haptic([8]);
    if (pin.length < PIN_LENGTH) {
      const next = [...pin, digit];
      setPin(next);
      if (next.length === PIN_LENGTH) {
        setTimeout(() => onComplete(next.join('')), 300);
      }
    }
  };

  const backspace = () => {
    haptic([6]);
    setPin(p => p.slice(0, -1));
  };

  const digits = [
    [1,2,3],[4,5,6],[7,8,9],[null,0,'⌫']
  ];

  return (
    <div className="animate-scale-in flex flex-col items-center gap-6">
      {/* PIN dots */}
      <div className="flex gap-4 mb-2">
        {Array.from({length: PIN_LENGTH}).map((_, i) => (
          <div key={i}
               className="w-3 h-3 rounded-full transition-all duration-200"
               style={{
                 background: i < pin.length ? '#6C63FF' : 'transparent',
                 border: `2px solid ${i < pin.length ? '#6C63FF' : '#333'}`
               }}/>
        ))}
      </div>

      {/* Numpad */}
      <div className="grid grid-cols-3 gap-4">
        {digits.flat().map((d, idx) => {
          if (d === null) return <div key={idx}/>;
          const isBack = d === '⌫';
          return (
            <button key={idx}
              onClick={() => isBack ? backspace() : press(d)}
              className="w-16 h-16 rounded-full glass flex items-center justify-center
                         text-xl font-semibold text-gs-text active:scale-90
                         transition-all duration-150"
              style={{border: '1px solid rgba(255,255,255,0.08)'}}>
              {d}
            </button>
          );
        })}
      </div>

      <button onClick={onBack}
        className="text-gs-muted text-sm mt-2 underline underline-offset-2">
        Cancel
      </button>
    </div>
  );
};

// ── Main App ──────────────────────────────────────────────────────────────
const STATES = {
  IDLE:       'IDLE',
  PIN:        'PIN',
  PROCESSING: 'PROCESSING',
  SUCCESS:    'SUCCESS',
  BLOCKED:    'BLOCKED',
};

function App() {
  const [appState, setAppState]   = useState(STATES.IDLE);
  const [modelReady, setModelReady] = useState(false);
  const [warmupCount, setWarmupCount] = useState(0);
  const [totalTaps, setTotalTaps] = useState(0);
  const [blocked, setBlocked]     = useState(0);
  const [epsilon, setEpsilon]     = useState(null);
  const [blockReason, setBlockReason] = useState('');
  const [lastVector, setLastVector] = useState(null);
  const [txnId, setTxnId]         = useState('');
  const [sseConnected, setSseConnected] = useState(false);
  const esRef = useRef(null);
  const pendingRef = useRef(false);

  const WARM_UP_N = 15;

  // ── Poll engine status ────────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch('/status');
        const d = await r.json();
        setModelReady(d.model_ready);
        setWarmupCount(d.warm_up_count || 0);
        setTotalTaps(d.total_taps || 0);
        setBlocked(d.blocked || 0);
        setEpsilon(d.epsilon || null);
        if (d.last_vector) setLastVector(d.last_vector);
      } catch(e) {}
    };
    poll();
    const id = setInterval(poll, 800);
    return () => clearInterval(id);
  }, []);

  // ── SSE stream for decisions ──────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const es = new EventSource('/events');
      esRef.current = es;
      es.onopen    = () => setSseConnected(true);
      es.onerror   = () => { setSseConnected(false); setTimeout(connect, 2000); };
      es.onmessage = (e) => {
        if (!pendingRef.current) return;
        const msg = JSON.parse(e.data);
        pendingRef.current = false;

        if (msg.decision === 'PERMIT') {
          haptic([50, 30, 80]);
          const id = 'GS' + Date.now().toString(36).toUpperCase();
          setTxnId(id);
          setAppState(STATES.SUCCESS);
        } else {
          haptic([200, 100, 200, 100, 200]);
          setBlockReason(msg.reason || 'Injection attack detected');
          setLastVector(msg.vector || null);
          setAppState(STATES.BLOCKED);
        }
      };
    };
    connect();
    return () => { if (esRef.current) esRef.current.close(); };
  }, []);

  const handlePayPress = () => {
    if (!modelReady) { haptic([15]); return; }
    haptic([12]);
    setAppState(STATES.PIN);
  };

  const handlePinComplete = (pin) => {
    haptic([20]);
    setAppState(STATES.PROCESSING);
    pendingRef.current = true;
    // 3s timeout fallback
    setTimeout(() => {
      if (pendingRef.current) {
        pendingRef.current = false;
        setAppState(STATES.IDLE);
      }
    }, 3500);
  };

  const handleReset = async () => {
    haptic([10]);
    await fetch('/reset', { method: 'POST' });
    setAppState(STATES.IDLE);
  };

  // ── RENDER ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gs-bg flex flex-col safe-top safe-bottom"
         style={{maxWidth:'430px', margin:'0 auto'}}>

      {/* Status bar */}
      <div className="flex items-center justify-between px-5 pt-3 pb-2">
        <div className="flex items-center gap-2">
          <ShieldIcon size={22} color={modelReady ? '#6C63FF' : '#444'}/>
          <span className="text-xs font-bold tracking-widest text-gs-muted">GHOSTSHIELD PAY</span>
        </div>
        <StatusBadge modelReady={modelReady} warmupCount={warmupCount} warmupTotal={WARM_UP_N}/>
      </div>

      {/* ── IDLE STATE ── */}
      {appState === STATES.IDLE && (
        <div className="flex-1 flex flex-col px-5 pt-4 pb-6 gap-4 animate-fade-up">

          {/* Balance card */}
          <div className="glass rounded-3xl p-6"
               style={{background:'linear-gradient(135deg,rgba(108,99,255,0.12),rgba(139,132,255,0.06))'}}>
            <p className="text-gs-muted text-xs tracking-widest mb-1">AVAILABLE BALANCE</p>
            <p className="text-4xl font-bold text-gs-text mb-1">₹84,200.00</p>
            <p className="text-gs-muted text-xs">••••  ••••  ••••  4821</p>
          </div>

          {/* Recipient */}
          <div className="glass rounded-2xl p-4 flex items-center gap-4">
            <div className="w-12 h-12 rounded-full flex items-center justify-center text-xl font-bold"
                 style={{background:'linear-gradient(135deg,#6C63FF,#8B84FF)'}}>
              G
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold">GhostShield Demo Store</p>
              <p className="text-xs text-gs-muted">ghostshield@upi</p>
            </div>
            <div className="flex items-center gap-1">
              <LockIcon size={14} color="#00D46A"/>
              <span className="text-xs text-gs-green">Verified</span>
            </div>
          </div>

          {/* Amount */}
          <div className="text-center py-4">
            <p className="text-gs-muted text-xs tracking-widest mb-2">PAYMENT AMOUNT</p>
            <p className="text-6xl font-bold shimmer-text">₹10,000</p>
            <p className="text-gs-muted text-xs mt-2">UPI Reference #GS-{Date.now().toString().slice(-8)}</p>
          </div>

          {/* Warmup progress (shown when not ready) */}
          {!modelReady && (
            <div className="glass rounded-2xl p-4">
              <div className="flex justify-between mb-2">
                <span className="text-xs text-gs-amber">Calibrating Biometric Model</span>
                <span className="text-xs text-gs-amber">{warmupCount}/{WARM_UP_N}</span>
              </div>
              <div className="w-full rounded-full h-1.5 overflow-hidden"
                   style={{background:'rgba(255,184,0,0.15)'}}>
                <div className="h-full rounded-full transition-all duration-500"
                     style={{
                       width: `${Math.min(100, (warmupCount/WARM_UP_N)*100)}%`,
                       background: 'linear-gradient(90deg,#FFB800,#FFD700)'
                     }}/>
              </div>
              <p className="text-gs-muted text-xs mt-2">
                Tap anywhere on screen naturally to complete calibration
              </p>
            </div>
          )}

          {/* PAY button */}
          <button
            onClick={handlePayPress}
            disabled={!modelReady}
            className="btn-pay w-full rounded-2xl py-5 text-white font-bold text-lg
                       tracking-wider shadow-glow-accent disabled:opacity-30
                       disabled:cursor-not-allowed mt-auto">
            {modelReady ? 'PAY ₹10,000' : 'Preparing Shield...'}
          </button>

          {/* Stats row */}
          <div className="flex justify-around text-center">
            {[
              {label:'Total Taps', value: totalTaps},
              {label:'Blocked',    value: blocked},
              {label:'ε (DBSCAN)', value: epsilon ? epsilon.toFixed(4) : '—'},
            ].map(({label, value}) => (
              <div key={label}>
                <p className="text-lg font-bold text-gs-text">{value}</p>
                <p className="text-xs text-gs-muted">{label}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── PIN STATE ── */}
      {appState === STATES.PIN && (
        <div className="flex-1 flex flex-col items-center justify-center px-5 gap-4 animate-fade-up">
          <ShieldIcon size={44} color="#6C63FF"/>
          <div className="text-center mb-2">
            <p className="text-xl font-bold">Enter UPI PIN</p>
            <p className="text-gs-muted text-sm mt-1">Biometric authentication in progress</p>
          </div>
          <PinPad onComplete={handlePinComplete} onBack={() => setAppState(STATES.IDLE)}/>
        </div>
      )}

      {/* ── PROCESSING STATE ── */}
      {appState === STATES.PROCESSING && (
        <div className="flex-1 flex flex-col items-center justify-center gap-6 animate-fade-up">
          {/* Animated rings */}
          <div className="relative w-28 h-28">
            <div className="absolute inset-0 rounded-full border-2 border-gs-accent opacity-20 animate-ping"/>
            <div className="absolute inset-2 rounded-full border-2 border-gs-accent opacity-40"
                 style={{animation:'spin 2s linear infinite'}}/>
            <div className="absolute inset-0 flex items-center justify-center">
              <ShieldIcon size={44} color="#6C63FF"/>
            </div>
          </div>
          <div className="text-center">
            <p className="text-xl font-bold">Authenticating</p>
            <p className="text-gs-muted text-sm mt-1">Analysing inertial signature...</p>
            <p className="text-gs-muted text-xs mt-1 font-mono">DBSCAN · F=ma · GhostShield™</p>
          </div>
          {/* Live vector if available */}
          {lastVector && lastVector.length >= 2 && (
            <div className="glass rounded-xl px-5 py-3 text-center"
                 style={{border:'1px solid rgba(108,99,255,0.2)'}}>
              <p className="text-xs text-gs-muted font-mono">
                Δt={lastVector[0]}ms · M={lastVector[1]}g
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── SUCCESS STATE ── */}
      {appState === STATES.SUCCESS && (
        <div className="flex-1 flex flex-col items-center justify-center px-5 gap-6 animate-scale-in"
             style={{background:'radial-gradient(ellipse at 50% 30%, rgba(0,212,106,0.08) 0%, transparent 70%)'}}>
          <CheckIcon size={72}/>
          <div className="text-center">
            <p className="text-3xl font-bold text-gs-green">Payment Successful</p>
            <p className="text-gs-text text-lg mt-2">₹10,000 paid</p>
            <p className="text-gs-muted text-sm mt-1">GhostShield Demo Store</p>
          </div>
          <div className="glass rounded-2xl p-4 w-full"
               style={{border:'1px solid rgba(0,212,106,0.2)'}}>
            <p className="text-xs text-gs-muted mb-1 font-mono">TRANSACTION ID</p>
            <p className="text-sm font-mono text-gs-green">{txnId}</p>
            {lastVector && lastVector.length >= 2 && (
              <>
                <div className="border-t border-gs-subtle mt-3 pt-3">
                  <p className="text-xs text-gs-muted font-mono mb-1">BIOMETRIC PROOF</p>
                  <p className="text-xs font-mono" style={{color:'rgba(0,212,106,0.8)'}}>
                    IMU Δt={lastVector[0]}ms · M_peak={lastVector[1]}g · label=0
                  </p>
                </div>
              </>
            )}
          </div>
          <button onClick={handleReset}
            className="w-full py-4 rounded-2xl text-gs-text font-semibold"
            style={{background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.08)'}}>
            New Payment
          </button>
        </div>
      )}

      {/* ── BLOCKED STATE ── */}
      {appState === STATES.BLOCKED && (
        <div className="flex-1 flex flex-col items-center justify-center px-5 gap-5 animate-scale-in"
             style={{background:'radial-gradient(ellipse at 50% 30%, rgba(255,59,48,0.10) 0%, transparent 70%)'}}>
          <div style={{animation:'pulseRed 1.1s ease-in-out infinite'}}>
            <BlockIcon size={80}/>
          </div>
          <div className="text-center">
            <p className="text-3xl font-bold text-gs-red">Payment Blocked</p>
            <p className="text-gs-muted text-sm mt-2">Ghost touch injection detected</p>
          </div>

          <div className="glass rounded-2xl p-4 w-full"
               style={{border:'1px solid rgba(255,59,48,0.25)', animation:'pulseRed 1.1s ease-in-out infinite'}}>
            <p className="text-xs font-mono text-gs-red mb-2">⚠ FRAUD ANALYSIS REPORT</p>
            <div className="space-y-1.5 font-mono text-xs" style={{color:'rgba(255,100,90,0.9)'}}>
              <div className="flex justify-between">
                <span className="text-gs-muted">SOURCE</span>
                <span>ADB / RAT Injection</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gs-muted">DBSCAN LABEL</span>
                <span>-1 (noise point)</span>
              </div>
              {lastVector && lastVector.length >= 2 && (
                <>
                  <div className="flex justify-between">
                    <span className="text-gs-muted">IMU M_peak</span>
                    <span>{lastVector[1]}g ≈ 0</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gs-muted">Δt (ms)</span>
                    <span>{lastVector[0]}</span>
                  </div>
                </>
              )}
              <div className="flex justify-between">
                <span className="text-gs-muted">NPCI DISPATCH</span>
                <span className="text-gs-red">SUPPRESSED</span>
              </div>
            </div>
            <div className="border-t border-gs-subtle mt-3 pt-2">
              <p className="text-xs text-gs-muted">{blockReason}</p>
            </div>
          </div>

          <button onClick={handleReset}
            className="w-full py-4 rounded-2xl font-semibold text-gs-red"
            style={{background:'rgba(255,59,48,0.08)', border:'1px solid rgba(255,59,48,0.2)'}}>
            Dismiss Alert
          </button>
        </div>
      )}

    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
</script>
</body>
</html>"""


# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route("/")
def index():
    _ensure_engine()
    return PAYMENT_UI, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/status")
def status():
    with _state_lock:
        return jsonify({
            # Scalar fields
            "model_ready":      shared_state["model_ready"],
            "warm_up_count":    shared_state["warm_up_count"],
            "warm_up_rejected": shared_state["warm_up_rejected"],
            "total_taps":       shared_state["total_taps"],
            "blocked":          shared_state["blocked"],
            "epsilon":          shared_state["epsilon"],
            "corpus_size":      shared_state["corpus_size"],
            "status":           shared_state["status"],
            "last_vector":      shared_state["last_vector"],
            "last_label":       shared_state["last_label"],
            "gate_decision":    shared_state["gate_decision"],
            # BUG-3 FIX: Array fields needed by dashboard scatter + history
            # Sent on every poll — capped to last 200 points to bound payload size
            "human_taps":       shared_state["human_taps"][-200:],
            "ghost_taps":       shared_state["ghost_taps"][-200:],
            "all_vectors":      shared_state["all_vectors"][-25:],
        })


@app.route("/events")
def events():
    """
    Server-Sent Events stream.
    React frontend connects here; engine pushes PERMIT/BLOCK decisions.
    """
    def generate():
        yield "data: {\"type\": \"connected\"}\n\n"
        while True:
            try:
                msg = event_queue.get(timeout=25)
                yield f"data: {json.dumps(msg)}\n\n"
            except Exception:
                # Heartbeat keepalive
                yield ": heartbeat\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        }
    )


@app.route("/reset", methods=["POST"])
def reset():
    # BUG-8 FIX: Drain event_queue before clearing state.
    # Without this, a stale BLOCK event sitting in the queue fires
    # the instant the next PAY press sets pendingRef=true, blocking
    # a legitimate payment before ADB even runs.
    drained = 0
    while not event_queue.empty():
        try:
            event_queue.get_nowait()
            drained += 1
        except Exception:
            break
    if drained:
        print(f"[RESET] Drained {drained} stale event(s) from queue")

    with _state_lock:
        shared_state["gate_decision"] = None
        shared_state["last_label"]    = None
        shared_state["status"]        = "SHIELD ACTIVE (Ready)"
    return jsonify({"ok": True, "drained": drained})


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    # Auto-detect laptop's LAN IP so the banner prints the exact URL to open
    import socket as _s
    try:
        _sock = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        _sock.connect(("8.8.8.8", 80))
        _laptop_ip = _sock.getsockname()[0]
        _sock.close()
    except Exception:
        _laptop_ip = "YOUR_LAPTOP_IP"

    print("\n" + "="*60)
    print("  GhostShield™ Payment App  v3.0")
    print("  Starting engine + Flask server...")
    print("="*60)
    _ensure_engine()
    print(f"\n  ✅ Open on phone browser:")
    print(f"     http://{_laptop_ip}:5000")
    print(f"\n  ✅ Add to Home Screen for native app (no Chrome UI)")
    print(f"\n  ✅ Dashboard (separate terminal):")
    print(f"     streamlit run dashboard.py")
    print("="*60 + "\n")
    # threaded=True: each SSE client gets its own thread
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
