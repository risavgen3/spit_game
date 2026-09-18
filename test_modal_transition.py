import subprocess
import tempfile
import os
import json
import time
import urllib.request
import base64
from websocket import create_connection

brave_path = r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'
user_data_dir = os.path.join(tempfile.gettempdir(), f'brave_test_{int(time.time())}')

proc = subprocess.Popen([
    brave_path, '--headless=new', '--remote-debugging-port=9222', '--remote-allow-origins=*',
    f'--user-data-dir={user_data_dir}', '--window-size=1280,950', 'http://127.0.0.1:5000'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    time.sleep(1.5)
    with urllib.request.urlopen('http://127.0.0.1:9222/json') as resp:
        tabs = json.loads(resp.read().decode())
    ws = create_connection(tabs[0]['webSocketDebuggerUrl'])

    msg_id = 1
    def send(method, params=None):
        global msg_id
        cid = msg_id
        msg_id += 1
        ws.send(json.dumps({'id': cid, 'method': method, 'params': params or {}}))
        while True:
            res = json.loads(ws.recv())
            if res.get('id') == cid:
                return res

    def eval_js(expr):
        res = send('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        return res.get('result', {}).get('result', {}).get('value')

    send('Page.enable')
    send('Runtime.enable')
    time.sleep(0.5)

    # 1. Trigger Game Over Modal as in user screenshot
    eval_js("document.getElementById('gameOverModal').classList.add('active');")
    eval_js("document.getElementById('gameOverTitle').textContent = 'DEFEAT!';")
    eval_js("document.getElementById('gameOverTitle').className = 'modal-title lose';")
    time.sleep(0.3)
    game_over_active = eval_js("document.getElementById('gameOverModal').classList.contains('active')")
    print('1. Game Over Modal active:', game_over_active)

    # 2. Click Select Mode button inside Game Over Modal
    print('2. Clicking Select Mode button...')
    eval_js("document.querySelectorAll('#gameOverModal button')[1].click()")
    time.sleep(0.4)

    # 3. Verify gameOverModal closed and waitingModal opened
    post_game_over = eval_js("document.getElementById('gameOverModal').classList.contains('active')")
    waiting_active = eval_js("document.getElementById('waitingModal').classList.contains('active')")
    print(f'3. After click -> Game Over active: {post_game_over} | Mode Selection active: {waiting_active}')
    assert not post_game_over, 'gameOverModal must be closed'
    assert waiting_active, 'waitingModal must be active'

    # 4. Capture screenshot of Mode Selection open
    res = send('Page.captureScreenshot', {'format': 'png'})
    img_data = res['result']['data']
    with open('brave_modal_transition_ok.png', 'wb') as f:
        f.write(base64.b64decode(img_data))
    print('[PASS] Successfully transitioned from Game Over to Mode Selection!')

    ws.close()
finally:
    proc.kill()
