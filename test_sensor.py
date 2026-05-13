# ============================================================
# test_sensor.py
# PURPOSE: Verify SensorServer app is streaming to your laptop
# RUN: python test_sensor.py
# ============================================================

import websocket
import json
import time

# ⚠️ CHANGE THIS TO YOUR PHONE'S IP FROM SENSORSERVER APP
PHONE_IP = "realme-10-Pro-5g.mshome.net"   # <-- PHONE'S IP HERE
PORT = 8080

print(f"Connecting to SensorServer at {PHONE_IP}:{PORT}")
print("Tap your phone screen a few times after connected...")
print("Press Ctrl+C to stop\n")

# ---- TEST 1: Accelerometer ----
def test_accelerometer():
    received = []
    
    def on_message(ws, msg):
        data = json.loads(msg)
        vals = data['values']
        t = time.time()
        mag = (vals[0]**2 + vals[1]**2 + vals[2]**2) ** 0.5
        print(f"[IMU] x={vals[0]:.3f} y={vals[1]:.3f} z={vals[2]:.3f} | mag={mag:.3f}g | t={t:.3f}")
        received.append(data)
        if len(received) >= 20:
            ws.close()

    def on_open(ws):
        print("✅ Accelerometer connected!\n")

    def on_error(ws, err):
        print(f"❌ Error: {err}")

    def on_close(ws, code, reason):
        print(f"\nAccelerometer test done. Got {len(received)} samples.")

    url = f"ws://{PHONE_IP}:{PORT}/sensor/connect?type=android.sensor.accelerometer"
    ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                 on_error=on_error, on_close=on_close)
    ws.run_forever()

# ---- TEST 2: Touchscreen ----
def test_touchscreen():
    received = []
    
    def on_message(ws, msg):
        data = json.loads(msg)
        print(f"[TOUCH] action={data['action']} x={data.get('x','?')} y={data.get('y','?')} "
              f"pressure={data.get('pressure','?')} size={data.get('size','?')}")
        received.append(data)
        if len(received) >= 5:
            ws.close()

    def on_open(ws):
        print("✅ Touchscreen connected! TAP YOUR PHONE NOW...\n")

    def on_error(ws, err):
        print(f"❌ Touch Error: {err}")

    def on_close(ws, code, reason):
        print(f"\nTouchscreen test done. Got {len(received)} touch events.")

    url = f"ws://{PHONE_IP}:{PORT}/touchscreen"
    ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                 on_error=on_error, on_close=on_close)
    ws.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("TEST 1: ACCELEROMETER")
    print("=" * 50)
    test_accelerometer()
    
    print("\n" + "=" * 50)
    print("TEST 2: TOUCHSCREEN (TAP PHONE 5 TIMES)")
    print("=" * 50)
    test_touchscreen()
    
    print("\n✅ ALL TESTS PASSED - Your setup is working!")