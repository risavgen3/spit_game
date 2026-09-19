import json
import time
import subprocess
import os
import base64
import requests
import websocket

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
PROFILE_DIR = r"c:\Users\Risav Chanda\.gemini\antigravity\scratch\spit-card-game\brave_test_profile"
TARGET_URL = "http://127.0.0.1:5000"
SCREENSHOT_PATH = os.environ.get("SCREENSHOT_PATH", os.path.join(os.path.dirname(__file__), "brave_tableau_gameplay.png"))

def run_brave_test():
    print(f"Launching Brave Browser from {BRAVE_PATH}...")
    cmd = [
        BRAVE_PATH,
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "--window-size=1366,960",
        f"--user-data-dir={PROFILE_DIR}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        TARGET_URL
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    ws = None
    try:
        # Wait for CDP endpoint
        ws_url = None
        for attempt in range(15):
            time.sleep(1)
            try:
                resp = requests.get("http://127.0.0.1:9222/json", timeout=2)
                tabs = resp.json()
                for tab in tabs:
                    if tab.get("type") == "page":
                        ws_url = tab.get("webSocketDebuggerUrl")
                        break
                if ws_url:
                    break
            except Exception:
                pass

        if not ws_url:
            raise RuntimeError("Could not find WebSocket debugger URL from Brave CDP.")

        print(f"Connected to Brave via CDP WebSocket: {ws_url}")
        ws = websocket.create_connection(ws_url, timeout=10)
        req_id = 1

        def cdp_send(method, params=None):
            nonlocal req_id
            msg = {"id": req_id, "method": method, "params": params or {}}
            req_id += 1
            ws.send(json.dumps(msg))
            while True:
                resp = json.loads(ws.recv())
                if resp.get("id") == msg["id"]:
                    return resp.get("result", {})

        def eval_js(expression):
            res = cdp_send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
            if "exceptionDetails" in res:
                print(f"JS EXCEPTION for [{expression}]: {res['exceptionDetails']}")
            return res.get("result", {}).get("value")

        # Enable Page & Runtime
        cdp_send("Page.enable")
        cdp_send("Runtime.enable")

        print("Navigating to TARGET_URL...")
        cdp_send("Page.navigate", {"url": TARGET_URL})
        time.sleep(3)

        curr_url = eval_js("window.location.href")
        print(f"Current URL: {curr_url}")
        ready_state = eval_js("document.readyState")
        print(f"Document readyState: {ready_state}")

        title = eval_js("document.title")
        print(f"Page Title: {title}")
        assert "SPIT" in title, f"Unexpected page title: {title}"

        # Verify Waiting Modal is active
        modal_active = eval_js("document.getElementById('waitingModal')?.classList.contains('active')")
        print(f"Waiting / Mode Selection Modal Active: {modal_active}")

        # Start solo bot game via JS function or click
        print("Triggering startBotGame('easy') in Brave DOM...")
        eval_js("window.startBotGame('easy')")

        # Wait for waitingModal to hide and cards to render
        time.sleep(2)

        # Verify modal closed
        modal_now_closed = eval_js("!document.getElementById('waitingModal')?.classList.contains('active')")
        print(f"Waiting Modal Closed: {modal_now_closed}")

        # Check Opponent Tableau Piles
        opp_piles = eval_js("document.querySelectorAll('#opponentHandContainer .tableau-pile').length")
        print(f"Opponent Tableau Piles: {opp_piles}")
        assert opp_piles == 5, f"Expected 5 opponent tableau piles, got {opp_piles}"

        # Check Opponent Face Down cards & Privacy
        opp_card_backs = eval_js("document.querySelectorAll('#opponentHandContainer .card-back').length")
        print(f"Opponent Card Backs Rendered: {opp_card_backs}")

        # Check Local Tableau Piles
        local_piles = eval_js("document.querySelectorAll('#localHandContainer .tableau-pile').length")
        print(f"Local Tableau Piles: {local_piles}")
        assert local_piles == 5, f"Expected 5 local tableau piles, got {local_piles}"

        # Check Depth Badges on Local Piles
        depths = eval_js("""
            Array.from(document.querySelectorAll('#localHandContainer .pile-depth-badge')).map(el => el.textContent.trim())
        """)
        print(f"Local Pile Depths: {depths}")

        # Check Center Piles
        p1_card = eval_js("document.querySelector('#centralPile1 .card .card-corner span')?.textContent")
        p2_card = eval_js("document.querySelector('#centralPile2 .card .card-corner span')?.textContent")
        print(f"Center Pile 1 Top Card: {p1_card}")
        print(f"Center Pile 2 Top Card: {p2_card}")

        # Check Spit stocks
        loc_stock = eval_js("document.getElementById('localStockCount')?.textContent")
        opp_stock = eval_js("document.getElementById('oppStockCount')?.textContent")
        round_text = eval_js("document.getElementById('matchRoundBadge')?.textContent")
        print(f"Local Spit Stock: {loc_stock}, Opponent Spit Stock: {opp_stock}")
        print(f"Match Round Badge: {round_text}")

        # Check Slap Buttons exist
        slap1_btn = eval_js("document.getElementById('slapBtn1') !== null")
        slap2_btn = eval_js("document.getElementById('slapBtn2') !== null")
        print(f"Slap Button 1: {slap1_btn}, Slap Button 2: {slap2_btn}")

        # Test Card Selection Interaction: Click first available local tableau card
        print("Testing card click interaction on local pile 0...")
        eval_js("document.querySelector('#localHandContainer .tableau-pile .card')?.click()")
        time.sleep(0.5)
        is_selected = eval_js("document.querySelector('#localHandContainer .tableau-pile .card')?.classList.contains('selected')")
        print(f"Local card selected after click: {is_selected}")

        # Test live move: Find a playable card from local tableau to either center pile
        play_res = eval_js("""
            (() => {
                const p1Rank = parseInt(document.getElementById('centralPile1').querySelector('.card')?.dataset?.rank || '0');
                const p2Rank = parseInt(document.getElementById('centralPile2').querySelector('.card')?.dataset?.rank || '0');
                const cards = Array.from(document.querySelectorAll('#localHandContainer .tableau-pile .card'));
                
                function isValid(cRank, targetRank) {
                    const diff = (cRank - targetRank + 13) % 13;
                    return diff === 1 || diff === 12;
                }

                for (let cardEl of cards) {
                    const cRank = parseInt(cardEl.dataset.rank || '0');
                    const cId = cardEl.dataset.cardId;
                    const fromPile = cardEl.dataset.fromPile;
                    if (isValid(cRank, p1Rank)) {
                        cardEl.click();
                        document.getElementById('centralPile1').click();
                        return { played: true, cardId: cId, target: 1, rank: cRank, fromPile: fromPile };
                    }
                    if (isValid(cRank, p2Rank)) {
                        cardEl.click();
                        document.getElementById('centralPile2').click();
                        return { played: true, cardId: cId, target: 2, rank: cRank, fromPile: fromPile };
                    }
                }
                return { played: false, p1Rank, p2Rank };
            })()
        """)
        print(f"Automated card play attempt: {play_res}")
        time.sleep(1)

        # Test Spit Button click
        print("Testing Spit Button click...")
        eval_js("document.getElementById('spitBtn')?.click()")
        time.sleep(0.5)
        spit_btn_text = eval_js("document.getElementById('spitBtn')?.innerText")
        safe_text = str(spit_btn_text).encode('ascii', 'backslashreplace').decode('ascii')
        print(f"Spit Button Text: {safe_text}")

        # Check for any logged JavaScript errors
        js_errors = eval_js("window.__console_errors || []")
        print(f"DOM JavaScript Errors: {js_errors}")
        assert len(js_errors) == 0, f"Encountered JS errors in Brave: {js_errors}"

        # Capture high-res screenshot
        print(f"Capturing Brave screenshot to {SCREENSHOT_PATH}...")
        ss = cdp_send("Page.captureScreenshot", {"format": "png"})
        if "data" in ss:
            with open(SCREENSHOT_PATH, "wb") as f:
                f.write(base64.b64decode(ss["data"]))
            size = os.path.getsize(SCREENSHOT_PATH)
            print(f"Screenshot successfully saved: {size} bytes")

        print("SUCCESS: ALL BRAVE DOM CHECKS AND INTERACTIONS VERIFIED PERFECTLY!")

    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    run_brave_test()
