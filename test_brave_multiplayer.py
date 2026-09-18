import subprocess
import tempfile
import os
import json
import time
import urllib.request
import base64
from websocket import create_connection

brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
user_data_dir = os.path.join(tempfile.gettempdir(), f"brave_multi_{int(time.time())}")
room_name = f"multiplayer_brave_{int(time.time())}"

p1_url = f"http://127.0.0.1:5000/?room={room_name}&player=Alice"
p2_url = f"http://127.0.0.1:5000/?room={room_name}&player=Bob"

print(f"Launching Brave for 2-Player Multiplayer Test (Room: {room_name})...")
proc = subprocess.Popen([
    brave_path,
    "--headless=new",
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    f"--user-data-dir={user_data_dir}",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-sync",
    "--window-size=1280,950",
    p1_url
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    # 1. Connect to Brave DevTools
    time.sleep(1.5)
    tabs = []
    for _ in range(15):
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json") as resp:
                tabs = json.loads(resp.read().decode())
                if tabs:
                    break
        except Exception:
            time.sleep(0.5)

    p1_tab = tabs[0]
    ws_p1_url = p1_tab.get("webSocketDebuggerUrl")
    print(f"[P1] Connected to Alice's Browser Tab: {ws_p1_url}")
    ws_p1 = create_connection(ws_p1_url)

    msg_id = 1
    def send_p1(method, params=None):
        global msg_id
        cid = msg_id
        msg_id += 1
        ws_p1.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            res = json.loads(ws_p1.recv())
            if res.get("id") == cid:
                return res

    def eval_p1(expr):
        res = send_p1("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value")

    def snap_p1(fname):
        res = send_p1("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["result"]["data"])
        with open(fname, "wb") as f:
            f.write(data)
        print(f"[SCREENSHOT] Saved: {fname} ({len(data)} bytes)")

    send_p1("Page.enable")
    send_p1("Runtime.enable")

    time.sleep(1.0)
    p1_role = eval_p1("document.getElementById('localNameLabel').textContent")
    p1_status = eval_p1("document.getElementById('gameStatusPill').textContent")
    print(f"[P1 DOM] Alice status: '{p1_status}', Label: '{p1_role}'")

    # 2. Open Bob (Player 2) in a second browser tab via CDP Target.createTarget
    print(f"\n--- Launching Player 2 (Bob) into Room '{room_name}' ---")
    create_res = send_p1("Target.createTarget", {"url": p2_url})
    p2_target_id = create_res.get("result", {}).get("targetId")
    print(f"[TARGET] Created Player 2 Tab Target ID: {p2_target_id}")

    time.sleep(1.0)
    # Find Bob's tab websocket
    with urllib.request.urlopen("http://127.0.0.1:9222/json") as resp:
        all_tabs = json.loads(resp.read().decode())
    p2_tab = next(t for t in all_tabs if p2_target_id in t.get("id", "") or "player=Bob" in t.get("url", ""))
    ws_p2_url = p2_tab.get("webSocketDebuggerUrl")
    print(f"[P2] Connected to Bob's Browser Tab: {ws_p2_url}")
    ws_p2 = create_connection(ws_p2_url)

    msg_p2_id = 1000
    def send_p2(method, params=None):
        global msg_p2_id
        cid = msg_p2_id
        msg_p2_id += 1
        ws_p2.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            res = json.loads(ws_p2.recv())
            if res.get("id") == cid:
                return res

    def eval_p2(expr):
        res = send_p2("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value")

    def snap_p2(fname):
        res = send_p2("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["result"]["data"])
        with open(fname, "wb") as f:
            f.write(data)
        print(f"[SCREENSHOT] Saved: {fname} ({len(data)} bytes)")

    send_p2("Page.enable")
    send_p2("Runtime.enable")

    # 3. Wait for Countdown to complete
    print("\n--- Both Players Connected: Waiting for Match Start Countdown ---")
    for sec in range(4):
        time.sleep(1.0)
        s1 = eval_p1("document.getElementById('gameStatusPill').textContent")
        s2 = eval_p2("document.getElementById('gameStatusPill').textContent")
        print(f"[T+{sec+1}s] Alice sees: '{s1}' | Bob sees: '{s2}'")

    # Verify both reached 'playing'
    p1_playing = eval_p1("lastKnownStatus")
    p2_playing = eval_p2("lastKnownStatus")
    print(f"\n[DOM CHECK] Alice status: {p1_playing} | Bob status: {p2_playing}")
    assert p1_playing == 'playing' and p2_playing == 'playing'

    # Check names and cards
    p1_local = eval_p1("document.getElementById('localNameLabel').textContent")
    p1_opp = eval_p1("document.getElementById('opponentNameLabel').textContent")
    p2_local = eval_p2("document.getElementById('localNameLabel').textContent")
    p2_opp = eval_p2("document.getElementById('opponentNameLabel').textContent")
    print(f"[P1 View] You: '{p1_local}' vs Opponent: '{p1_opp}'")
    print(f"[P2 View] You: '{p2_local}' vs Opponent: '{p2_opp}'")

    # Capture screenshots of both players in active 2-player match
    snap_p1("brave_multiplayer_p1.png")
    snap_p2("brave_multiplayer_p2.png")

    # 4. Test Strict Simultaneous SPIT in 2-Player Multiplayer
    print("\n--- Testing Strict Simultaneous SPIT in 2-Player Multiplayer ---")
    print("[ACTION] Player 1 (Alice) calls SPIT...")
    eval_p1("requestSpit()")
    time.sleep(0.4)

    p1_btn = eval_p1("document.getElementById('spitBtn').textContent")
    p1_msg = eval_p1("document.getElementById('spitStatusMsg').textContent")
    p2_btn = eval_p2("document.getElementById('spitBtn').textContent")
    p2_msg = eval_p2("document.getElementById('spitStatusMsg').textContent")
    pile1_before = eval_p1("document.getElementById('pile1Count').textContent")

    print(f"[P1 DOM] Button: '{p1_btn}' | Subtitle: '{p1_msg}'")
    print(f"[P2 DOM] Button: '{p2_btn}' | Subtitle: '{p2_msg}'")
    print(f"[P1 DOM] Central Pile 1 count before Bob flips: {pile1_before}")

    assert "READY" in p1_btn, f"Expected READY on P1, got {p1_btn}"
    assert "FLIP READY" in p2_btn, f"Expected FLIP READY on P2, got {p2_btn}"
    assert pile1_before == "1", "Central pile must NOT flip until Player 2 agrees!"
    print("[PASS] Verified: Alice cannot flip unilaterally. Bob is prompted with FLIP READY!")

    snap_p1("brave_multiplayer_spit_sync.png")

    print("\n[ACTION] Player 2 (Bob) now taps SPIT to trigger simultaneous consensus...")
    eval_p2("requestSpit()")
    time.sleep(0.5)

    pile1_after = eval_p1("document.getElementById('pile1Count').textContent")
    p1_btn_after = eval_p1("document.getElementById('spitBtn').textContent")
    print(f"[DOM AFTER SYNC] Central Pile 1 count: {pile1_after} (was {pile1_before})")
    print(f"[DOM AFTER SYNC] Alice Spit button reset to: '{p1_btn_after}'")

    assert int(pile1_after) == int(pile1_before) + 1, "Piles must flip when both players agree!"
    print("[PASS] Simultaneous Spit Flip confirmed in real-time across both browser windows!")

    ws_p1.close()
    ws_p2.close()
    print("\n[SUCCESS] All 2-Player Multiplayer DOM checks in Brave passed with 100% success!")

finally:
    proc.kill()
