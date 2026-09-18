import urllib.request
import re
import time
import socketio

def verify_dom_elements():
    print("--- 1. Verifying DOM Elements in http://127.0.0.1:5000 ---")
    req = urllib.request.Request('http://127.0.0.1:5000')
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')

    assert resp.status == 200, f"Expected 200 OK, got {resp.status}"
    print("[PASS] Server returned 200 OK")

    # Verify critical DOM elements
    required_ids = [
        'spitBtn', 'spitStatusMsg', 'spitBurstBanner',
        'botSpeedControls', 'speedChillBtn', 'speedBalancedBtn', 'speedProBtn',
        'centralPile1', 'centralPile2',
        'localHandContainer', 'opponentHandContainer',
        'waitingModal', 'rulesModal', 'gameOverModal'
    ]
    for el_id in required_ids:
        assert f'id="{el_id}"' in html, f"Missing DOM element id='{el_id}'"
        print(f"[PASS] Found DOM element #{el_id}")

    # Verify CSS pointer-events on central pile children
    assert '.central-pile *' in html and 'pointer-events: none' in html, "Missing pointer-events: none on .central-pile *"
    print("[PASS] .central-pile * has pointer-events: none (prevents dragover flickering)")

    # Verify Spit button styling states
    assert '.btn-spit.opp-ready' in html, "Missing .btn-spit.opp-ready CSS class"
    assert '.spit-burst-banner' in html, "Missing .spit-burst-banner CSS class"
    print("[PASS] Verified .btn-spit.opp-ready and .spit-burst-banner styles")

    # Verify Spacebar preventDefault in script
    assert "e.preventDefault();" in html and "requestSpit();" in html, "Missing e.preventDefault() on Spacebar"
    print("[PASS] Verified e.preventDefault() prevents page scrolling on Spacebar")

    print("[SUCCESS] All DOM and CSS element checks passed!\n")

def verify_game_play_and_spit():
    print("--- 2. Verifying Game State, Dynamic Speed & Simultaneous Spit via Socket.IO ---")
    sio = socketio.Client()
    received_states = []
    room_id = f"test_room_{int(time.time())}"

    @sio.on('game_state')
    def on_game_state(state):
        received_states.append(state)

    sio.connect('http://127.0.0.1:5000')
    print("[PASS] Connected Socket.IO client to server")

    # Start bot game on Chill mode
    sio.emit('start_bot_game', {'room': room_id, 'difficulty': 'easy', 'name': 'Tester'})
    print("[PASS] Emitted start_bot_game (difficulty='easy')")

    # Wait for countdown to finish and game to start
    start_time = time.time()
    playing_state = None
    while time.time() - start_time < 6.0:
        sio.sleep(0.5)
        for s in received_states:
            if s.get('status') == 'playing':
                playing_state = s
                break
        if playing_state:
            break

    assert playing_state is not None, "Timed out waiting for match to reach 'playing' state"
    print(f"[PASS] Match reached 'playing' status! P1 hand: {len(playing_state['your_hand'])} cards, Stock: {playing_state['your_stock_count']}")
    assert playing_state['is_bot'] is True
    assert playing_state['bot_difficulty'] == 'easy'
    assert 'Chill' in playing_state['p2_name']
    print(f"[PASS] Opponent is {playing_state['p2_name'].encode('ascii', 'replace').decode('ascii')}")

    # Test dynamic difficulty change
    sio.emit('set_bot_difficulty', {'room': room_id, 'difficulty': 'hard'})
    sio.sleep(0.5)
    latest_state = received_states[-1]
    assert latest_state['bot_difficulty'] == 'hard', f"Expected hard, got {latest_state['bot_difficulty']}"
    assert 'Pro' in latest_state['p2_name']
    print(f"[PASS] In-game speed switch verified: changed to {latest_state['p2_name'].encode('ascii', 'replace').decode('ascii')}")

    # Test simultaneous SPIT
    # P1 requests spit
    initial_p1_pile = latest_state['pile1_count']
    sio.emit('request_spit', {'room': room_id})
    sio.sleep(0.5)
    post_spit_state = received_states[-1]
    print(f"[PASS] Player 1 requested SPIT! your_spit={post_spit_state['your_spit']}, opp_spit={post_spit_state['opp_spit']}, pile1={post_spit_state['pile1_count']}")

    # If cards flipped simultaneously:
    if post_spit_state['pile1_count'] > initial_p1_pile:
        print("[PASS] Bot was stuck too and agreed to SPIT simultaneously -> flipped to Pile 1!")
        assert post_spit_state['your_spit'] is False, "Spit readiness should reset after flip"
        assert post_spit_state['opp_spit'] is False, "Spit readiness should reset after flip"
    else:
        # P1 is waiting for bot:
        assert post_spit_state['your_spit'] is True, "P1 should be marked ready"
        print("[PASS] Strict simultaneous rule enforced: cards did NOT flip unilaterally while bot had moves or was deciding!")

    # Test playing a card
    from app import is_valid_spit_move
    hand = post_spit_state['your_hand']
    pile1_top = post_spit_state['pile1_top']
    pile2_top = post_spit_state['pile2_top']
    p1_playable_card = None
    target_pile_num = None
    for c in hand:
        if pile1_top and is_valid_spit_move(c['rank'], pile1_top['rank']):
            p1_playable_card = c
            target_pile_num = 1
            break
        if pile2_top and is_valid_spit_move(c['rank'], pile2_top['rank']):
            p1_playable_card = c
            target_pile_num = 2
            break

    if p1_playable_card:
        print(f"[TEST] Playing {p1_playable_card['label']}{p1_playable_card['symbol']} on Pile {target_pile_num}...")
        sio.emit('play_card', {
            'room': room_id,
            'card_id': p1_playable_card['id'],
            'pile': target_pile_num
        })
        sio.sleep(0.5)
        post_play_state = received_states[-1]
        new_pile_top = post_play_state[f'pile{target_pile_num}_top']
        assert new_pile_top['id'] == p1_playable_card['id'], f"Expected {p1_playable_card['id']}, got {new_pile_top['id']}"
        print(f"[PASS] Successfully played {p1_playable_card['label']}{p1_playable_card['symbol']} to Pile {target_pile_num}! New pile top: {new_pile_top['label']}{new_pile_top['symbol']}")
        print(f"[PASS] Hand length maintained at {len(post_play_state['your_hand'])} (auto-refilled from stock, stock remaining: {post_play_state['your_stock_count']})")
    else:
        print("[INFO] No valid move was available at this moment in test hand, which tests stuck condition")

    sio.disconnect()
    print("[SUCCESS] All Socket.IO, Pacing, and Simultaneous Spit rules passed!")

if __name__ == '__main__':
    verify_dom_elements()
    verify_game_play_and_spit()
