import subprocess
import sys
import time
import os
os.system('') 

TAP_X = 540     
TAP_Y = 1850    

# Injection sequence
NUM_INJECTIONS    = 3       
DELAY_BETWEEN_SEC = 3.0     
COUNTDOWN_SEC     = 5       


# =============================================================================
# UTILITIES
# =============================================================================

def _color(code: str, text: str) -> str:
    """ANSI color codes for terminal output."""
    colors = {
        "red":    "\033[91m",
        "green":  "\033[92m",
        "yellow": "\033[93m",
        "blue":   "\033[94m",
        "purple": "\033[95m",
        "cyan":   "\033[96m",
        "white":  "\033[97m",
        "bold":   "\033[1m",
        "reset":  "\033[0m",
    }
    return f"{colors.get(code,'')}{text}{colors['reset']}"


def _banner():
    print()
    print(_color("purple", "="*62))
    print(_color("bold",   "  GhostShield™  v3.0  —  Ghost Tap Injector"))
    print(_color("purple", "  The Physics Invariant Demo: F = m × a"))
    print(_color("purple", "="*62))
    print()
    print(_color("cyan", "  WHAT HAPPENS:"))
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │ ADB injects touch event at ({}, {})          │".format(
        str(TAP_X).ljust(4), str(TAP_Y).ljust(4)))
    print("  │ Phone screen: PAY button animates — NO finger touch │")
    print("  │ IMU response: M_peak ≈ 0.000g  (zero physical force)│")
    print("  │ DBSCAN label: -1  (noise point outside ε-boundary)  │")
    print("  │ Payment app:  🚫 PAYMENT BLOCKED — FRAUD DETECTED   │")
    print("  │ Dashboard:    Red ✗ appears at origin (0, 0)        │")
    print("  └─────────────────────────────────────────────────────┘")
    print()


def check_adb() -> bool:
    """Verify ADB is installed and phone is connected."""
    # Check ADB binary exists
    try:
        r = subprocess.run(["adb", "version"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            print(_color("red", "  ❌ ADB not found. Install Android Platform Tools."))
            print(_color("yellow", "  → https://developer.android.com/tools/releases/platform-tools"))
            return False
        adb_ver = r.stdout.split("\n")[0].strip()
        print(_color("green", f"  ✅ {adb_ver}"))
    except FileNotFoundError:
        print(_color("red", "  ❌ ADB not in PATH."))
        print(_color("yellow", "  → Add C:\\adb to System Environment Variables → Path"))
        return False

    # Check device connected
    r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
    lines = [
        l.strip() for l in r.stdout.strip().split("\n")[1:]
        if l.strip() and "offline" not in l and "unauthorized" not in l
    ]

    if not lines:
        print(_color("red", "\n  ❌ No ADB device found!"))
        print(_color("yellow", "  Fix checklist:"))
        print("    1. Connect phone via USB cable")
        print("    2. Phone Settings → Developer Options → USB Debugging = ON")
        print("    3. Look for 'Allow USB Debugging?' popup on phone → ALLOW")
        print("    4. Run: adb devices  (should show your device)")

        # Check for unauthorized
        unauth = [l for l in r.stdout.strip().split("\n")[1:] if "unauthorized" in l]
        if unauth:
            print(_color("yellow", "\n  ⚠ Device shows UNAUTHORIZED:"))
            print("    → Check phone screen for RSA key popup and tap ALLOW")

        return False

    print(_color("green", f"  ✅ Device connected: {lines[0]}"))
    return True


def get_screen_dimensions() -> tuple[int, int]:
    """Get phone screen resolution via ADB."""
    try:
        r = subprocess.run(
            ["adb", "shell", "wm", "size"],
            capture_output=True, text=True, timeout=5
        )
        # Output: "Physical size: 1080x2400"
        if "x" in r.stdout:
            parts = r.stdout.strip().split(":")[-1].strip().split("x")
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 1080, 2400   # Realme 10 Pro 5G default


def inject_ghost_tap(x: int, y: int, tap_num: int, total: int) -> bool:
    """
    Inject one synthetic touch event via ADB.

    Technical detail:
        adb shell input tap X Y
        → Android OS creates a MotionEvent.ACTION_DOWN at (X,Y)
        → No physical glass contact occurs
        → No mechanical force transmitted to chassis
        → MEMS accelerometer: M_peak ≈ 0.000g
        → GhostShield DBSCAN: distance >> ε → label = -1
    """
    print()
    print(_color("yellow", f"  ── INJECTION {tap_num}/{total} ──────────────────────────────"))
    print(_color("white",  f"  Target:  ({x}, {y}) on phone screen"))
    print(_color("white",   "  Method:  adb shell input tap"))
    print(_color("cyan",    "  Physics: NO physical force applied to glass"))
    print(_color("cyan",    "  IMU:     Expecting M_peak ≈ 0.000g"))

    t_start = time.time()
    result  = subprocess.run(
        ["adb", "shell", "input", "tap", str(x), str(y)],
        capture_output=True, text=True, timeout=8
    )
    elapsed = (time.time() - t_start) * 1000

    if result.returncode == 0:
        print(_color("green",  f"  ✅ ADB tap injected ({elapsed:.0f}ms)"))
        print(_color("red",    "  ⚠ Watch phone screen → button animates with NO finger"))
        print(_color("red",    "  ⚠ Watch dashboard   → red X should appear at (0, 0)"))
        print(_color("red",    "  ⚠ Watch payment app → 🚫 PAYMENT BLOCKED"))
        return True
    else:
        print(_color("red", f"  ❌ ADB error: {result.stderr.strip()}"))
        return False


def projector_countdown(seconds: int, message: str):
    """Countdown with terminal animation — keeps audience attention."""
    print()
    print(_color("bold", f"  {message}"))
    for i in range(seconds, 0, -1):
        bar = "█" * (seconds - i + 1) + "░" * (i - 1)
        sys.stdout.write(
            f"\r  [{bar}] {i}s  "
        )
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " "*50 + "\r")
    sys.stdout.flush()


# =============================================================================
# MAIN DEMO SEQUENCE
# =============================================================================

def main():
    _banner()

    # ── Step 1: ADB check ────────────────────────────────────────────────
    print(_color("bold", "  STEP 1 — Checking ADB connection"))
    if not check_adb():
        print(_color("red", "\n  Cannot proceed. Fix ADB connection first.\n"))
        sys.exit(1)

    # ── Step 1b: Quick coordinate test ──────────────────────────────────
    print()
    print(_color("bold", "  STEP 1b — Coordinate verification (BUG-6 FIX)"))
    print(_color("cyan", f"  Current TAP_X={TAP_X}  TAP_Y={TAP_Y}"))
    print("  Make sure phone shows payment_app.py UI (http://LAPTOP_IP:5000)")
    ans = input(_color("yellow",
        "  Fire ONE test tap to verify PAY button coordinates? [y/N]: "
    )).strip().lower()
    if ans == "y":
        print(_color("cyan", "  Firing test tap..."))
        subprocess.run(
            ["adb", "shell", "input", "tap", str(TAP_X), str(TAP_Y)],
            capture_output=True, text=True, timeout=5
        )
        print(_color("white",
            "  Check phone: did the PAY button highlight/animate?\n"
            "  If YES → coordinates are correct, proceed.\n"
            "  If NO  → Ctrl+C, update TAP_Y in ghost_injector.py, rerun.\n"
        ))
        input(_color("yellow", "  Press ENTER to continue or Ctrl+C to abort...  "))

    # ── Step 2: Screen info ──────────────────────────────────────────────
    w, h = get_screen_dimensions()
    print(_color("cyan", f"\n  Screen resolution: {w} × {h} px"))
    print(_color("cyan", f"  PAY button target: ({TAP_X}, {TAP_Y})"))

    # Sanity check coordinates
    if TAP_X > w or TAP_Y > h:
        print(_color("yellow",
            f"\n  ⚠ Warning: coordinates ({TAP_X},{TAP_Y}) exceed screen {w}×{h}"))
        print(_color("yellow",
            "  Update TAP_X and TAP_Y at top of ghost_injector.py"))

    # ── Step 3: Confirm ──────────────────────────────────────────────────
    print()
    print(_color("bold", "  BEFORE INJECTING — confirm this checklist:"))
    print("  □ GhostShield dashboard open on projector (streamlit run dashboard.py)")
    print("  □ Payment app showing on phone (http://LAPTOP_IP:5000)")
    print("  □ Phone payment UI shows: ◈ SHIELD ACTIVE")
    print("  □ Phone on PAY ₹10,000 screen")
    print("  □ Audience watching both phone AND dashboard")
    print()
    input(_color("yellow", "  Press ENTER when ready to begin injection sequence... "))

    # ── Step 4: Dramatic countdown ──────────────────────────────────────
    projector_countdown(
        COUNTDOWN_SEC,
        "🎬  Ghost tap injection starting in..."
    )

    # ── Step 5: Injection loop ───────────────────────────────────────────
    success_count = 0
    for i in range(1, NUM_INJECTIONS + 1):
        ok = inject_ghost_tap(TAP_X, TAP_Y, i, NUM_INJECTIONS)
        if ok:
            success_count += 1

        if i < NUM_INJECTIONS:
            print()
            print(_color("cyan", f"  Waiting {DELAY_BETWEEN_SEC:.0f}s for engine to process..."))
            time.sleep(DELAY_BETWEEN_SEC)

    # ── Step 6: Summary ──────────────────────────────────────────────────
    print()
    print(_color("purple", "="*62))
    print(_color("bold",   "  INJECTION SEQUENCE COMPLETE"))
    print(_color("purple", "="*62))
    print(_color("white",  f"  Injections fired:  {success_count}/{NUM_INJECTIONS}"))
    print(_color("green",  "  Expected results:"))
    print("  · Each ghost tap appeared on phone with NO finger contact")
    print("  · Dashboard shows red ✗ markers clustered near (0, 0)")
    print("  · Payment app showed: 🚫 PAYMENT BLOCKED — FRAUD DETECTED")
    print("  · Terminal showed:  GHOST  label=-1  dist >> ε")
    print()
    print(_color("cyan", "  THE EXPLANATION (say this to your audience):"))
    print()
    print(_color("white",
        '  "The malware sent a structurally perfect touch event.\n'
        '   The capacitive screen registered it.\n'
        '   The Android OS accepted it.\n'
        '   The PAY button responded.\n'
        '   But the malware forgot Newton\'s Second Law.\n'
        '   No physical mass contacted the glass.\n'
        '   No force was applied.\n'
        '   No chassis vibrated.\n'
        '   The IMU registered: 0.000g.\n'
        '   GhostShield did not need to know this malware.\n'
        '   It only needed to know this tap had no body behind it.\n'
        '   That is the unbreakable gate."'
    ))
    print()
    print(_color("purple", "="*62))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(_color("yellow", "\n\n  Demo interrupted by user."))
        sys.exit(0)
