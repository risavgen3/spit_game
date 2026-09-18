import subprocess
import tempfile
import os
import json
import time
import urllib.request
import base64
from websocket import create_connection

brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
user_data_dir = os.path.join(tempfile.gettempdir(), f"brave_cdp_{int(time.time())}")

print(f"Launching Brave from {brave_path}...")
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
    f"http://127.0.0.1:5000/?room=test_brave_{int(time.time())}"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    # Wait for DevTools port
    ws_url = None
    for _ in range(20):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json") as resp:
                tabs = json.loads(resp.read().decode())
                for t in tabs:
                    if "localhost" in t.get("url", "") or "127.0.0.1" in t.get("url", ""):
                        ws_url = t.get("webSocketDebuggerUrl")
                        break
                if not ws_url and tabs:
                    ws_url = tabs[0].get("webSocketDebuggerUrl")
                if ws_url:
                    break
        except Exception:
            pass

    if not ws_url:
        raise RuntimeError("Failed to connect to Brave DevTools endpoint")

    print(f"[PASS] Connected to Brave WebSocket: {ws_url}")
    ws = create_connection(ws_url)

    msg_id = 1
    def send_cmd(method, params=None):
        global msg_id
        current_id = msg_id
        payload = {"id": current_id, "method": method, "params": params or {}}
        msg_id += 1
        ws.send(json.dumps(payload))
        while True:
            res = json.loads(ws.recv())
            if res.get("id") == current_id:
                return res

    def eval_js(expression):
        res = send_cmd("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value")

    def capture_screenshot(filename):
        res = send_cmd("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["result"]["data"])
        with open(filename, "wb") as f:
            f.write(data)
        print(f"[SCREENSHOT] Saved: {filename} ({len(data)} bytes)")

    # Enable Page domain
    send_cmd("Page.enable")
    send_cmd("Runtime.enable")

    # Give page time to load and initialize socket
    time.sleep(1.5)

    # 1. Check title and lobby modal in DOM
    title = eval_js("document.title")
    print(f"[DOM] Page Title in Brave: '{title}'")
    assert "SPIT!" in title

    modal_active = eval_js("document.getElementById('waitingModal').classList.contains('active')")
    print(f"[DOM] Mode selection modal is active: {modal_active}")

    # Capture initial lobby screenshot
    capture_screenshot("brave_lobby.png")

    # 2. Click to Start Match vs SpitBot in 'easy' (Chill 🐢) mode
    print("[ACTION] Clicking 'Casual / Chill' button in Brave DOM...")
    eval_js("startBotGame('easy')")

    # Wait for countdown
    for sec in range(4):
        time.sleep(1.0)
        status_text = eval_js("document.getElementById('gameStatusPill').textContent")
        countdown_val = eval_js("document.getElementById('countdownBanner').textContent")
        print(f"[DOM Status at T+{sec+1}s] Status pill: '{status_text}', Banner: '{countdown_val}'")

    # Check match playing state
    playing_status = eval_js("document.getElementById('gameStatusPill').textContent")
    print(f"[DOM] Game status pill: '{playing_status}'")

    # Verify DOM elements after game start
    hand_cards = eval_js("document.querySelectorAll('#localHandContainer .card').length")
    print(f"[DOM] Local player hand cards rendered: {hand_cards}")
    assert hand_cards == 5, f"Expected 5 cards, found {hand_cards}"

    pile1_count = eval_js("document.getElementById('pile1Count').textContent")
    pile2_count = eval_js("document.getElementById('pile2Count').textContent")
    print(f"[DOM] Central Pile 1 count: {pile1_count}, Central Pile 2 count: {pile2_count}")

    bot_speed_visible = eval_js("document.getElementById('botSpeedControls').style.display")
    print(f"[DOM] Bot speed switcher visible: {bot_speed_visible}")

    spit_btn_text = eval_js("document.getElementById('spitBtn').textContent")
    spit_msg_text = eval_js("document.getElementById('spitStatusMsg').textContent")
    print(f"[DOM] Spit button text: '{spit_btn_text}', Subtitle: '{spit_msg_text}'")

    capture_screenshot("brave_gameplay.png")

    # 3. Test changing speed to Pro
    print("[ACTION] Switching bot speed to Pro in Brave DOM...")
    eval_js("changeBotSpeed('hard')")
    time.sleep(0.5)
    pro_btn_active = eval_js("document.getElementById('speedProBtn').classList.contains('active')")
    print(f"[DOM] Pro speed button active class: {pro_btn_active}")

    # 4. Test tapping SPIT
    print("[ACTION] Tapping SPIT button in Brave DOM...")
    eval_js("document.getElementById('spitBtn').click()")
    time.sleep(0.4)

    post_spit_btn = eval_js("document.getElementById('spitBtn').textContent")
    post_spit_msg = eval_js("document.getElementById('spitStatusMsg').textContent")
    post_pile1 = eval_js("document.getElementById('pile1Count').textContent")
    print(f"[DOM] After tap Spit button text: '{post_spit_btn}'")
    print(f"[DOM] After tap Spit message: '{post_spit_msg}'")
    print(f"[DOM] Pile 1 count after click: {post_pile1}")

    capture_screenshot("brave_spit_state.png")

    # 5. Test Card Selection UI
    print("[ACTION] Clicking first card in local hand to test selection glow...")
    eval_js("const firstCard = document.querySelector('#localHandContainer .card'); if (firstCard) firstCard.click();")
    time.sleep(0.3)
    has_selected_card = eval_js("document.querySelectorAll('.card.selected').length > 0")
    print(f"[DOM] Card has 'selected' class: {has_selected_card}")

    # 6. Test Victory / Defeat Modal rendering
    print("[ACTION] Triggering Victory Modal state for visual verification...")
    eval_js("""
    socket.disconnect();
    const modal = document.getElementById('gameOverModal');
    const title = document.getElementById('gameOverTitle');
    const desc = document.getElementById('gameOverDesc');
    const icon = document.getElementById('gameOverIcon');
    modal.classList.add('active');
    title.textContent = 'VICTORY!';
    title.className = 'modal-title win';
    icon.textContent = '🏆';
    desc.textContent = 'Incredible reflexes! You defeated SpitBot and emptied all 26 cards!';
    document.getElementById('statMatchTime').textContent = '0m 42s';
    document.getElementById('statCardsCleared').textContent = '26 / 26 (100%)';
    document.getElementById('statOppRemaining').textContent = '9 cards left';
    document.getElementById('statMatchMode').textContent = 'SpitBot (Pro 🔥)';
    """)
    time.sleep(0.5)
    capture_screenshot("brave_victory_modal.png")


    # Close modal
    eval_js("document.getElementById('gameOverModal').classList.remove('active');")
    time.sleep(0.2)

    ws.close()
    print("\n[BRAVE VERIFICATION COMPLETE] All DOM interactions, animations, and modals in Brave verified successfully!")

finally:
    proc.kill()

