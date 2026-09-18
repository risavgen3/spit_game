import os

# Eventlet monkey-patching MUST occur before importing socket/threading/time for Gunicorn on Render
try:
    import eventlet  # type: ignore
    eventlet.monkey_patch()
    async_mode = 'eventlet'
except Exception:
    async_mode = 'threading'

import random
import uuid
import threading
import time
from typing import Literal
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room  # type: ignore

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

if os.environ.get('ASYNC_MODE') == 'eventlet':
    async_mode = 'eventlet'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)  # type: ignore

# --- Card Engine & Rules ---
SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
SUIT_SYMBOLS = {'hearts': '♥', 'diamonds': '♦', 'clubs': '♣', 'spades': '♠'}
SUIT_COLORS = {'hearts': 'red', 'diamonds': 'red', 'clubs': 'black', 'spades': 'black'}
RANK_LABELS = {
    1: 'A', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6',
    7: '7', 8: '8', 9: '9', 10: '10', 11: 'J', 12: 'Q', 13: 'K'
}

def create_card(rank, suit, face_up=False):
    return {
        'id': str(uuid.uuid4()),
        'rank': rank,
        'suit': suit,
        'label': RANK_LABELS[rank],
        'symbol': SUIT_SYMBOLS[suit],
        'color': SUIT_COLORS[suit],
        'face_up': face_up
    }

def create_deck():
    cards = [create_card(rank, suit) for suit in SUITS for rank in range(1, 14)]
    random.shuffle(cards)
    return cards

def is_valid_spit_move(card_rank: int, target_top_rank: int) -> bool:
    """
    Rule Enforcement (K-A-2-3 Continuity):
    Valid if:
    - standard +/- 1 difference (e.g. 7 on 6 or 8)
    - King (13) on Ace (1), Ace (1) on King (13), 2 on Ace (1), Ace (1) on 2.
    Formula (card_rank - target_top_rank) % 13 in (1, 12) captures all wrap and standard steps.
    """
    diff = (card_rank - target_top_rank) % 13
    return diff in (1, 12)

# --- Spit/Slam Tableau Deal ---
def deal_tableau_from_cards(cards):
    """
    Spit Rules: Deal up to 5 tableau piles of depths [1, 2, 3, 4, 5] (15 cards max).
    The top card of each occupied pile is face_up = True, underneath cards are face_up = False.
    Any remaining cards become the player's spit_stock.
    """
    pool = list(cards)
    tableau = [[], [], [], [], []]
    for pile_idx in range(5):
        depth = pile_idx + 1
        for d in range(depth):
            if pool:
                c = pool.pop(0)
                is_top = (d == depth - 1)
                c['face_up'] = is_top
                tableau[pile_idx].append(c)
        if tableau[pile_idx]:
            tableau[pile_idx][-1]['face_up'] = True
    spit_stock = pool
    for c in spit_stock:
        c['face_up'] = False
    return tableau, spit_stock

# --- Room Management ---
rooms = {}
rooms_lock = threading.RLock()

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.lock = threading.RLock()
        self.p1_sid = None
        self.p2_sid = None
        self.is_bot_p2 = False
        self.bot_difficulty = 'normal'  # 'easy', 'normal', 'hard'
        self.players = {}  # sid -> {'role': 'p1'/'p2', 'name': str}
        self.status = 'waiting'  # 'waiting', 'countdown', 'playing', 'game_over'
        self.pile1 = []
        self.pile2 = []
        self.p1_tableau = [[], [], [], [], []]
        self.p1_spit_stock = []
        self.p2_tableau = [[], [], [], [], []]
        self.p2_spit_stock = []
        self.p1_spit = False
        self.p2_spit = False
        self.can_slap = False
        self.round_num = 1
        self.winner = None
        self.countdown_val = 0
        self.start_time = None
        self.match_duration = 0
        self.game_round_id = 0
        self.log = []

    def log_event(self, msg):
        timestamp = time.strftime('%H:%M:%S')
        self.log.append(f'[{timestamp}] {msg}')
        if len(self.log) > 20:
            self.log.pop(0)

    def add_bot(self, difficulty='normal'):
        with self.lock:
            bot_sid = f"bot_{self.room_id}"
            self.p2_sid = bot_sid
            self.is_bot_p2 = True
            self.bot_difficulty = difficulty
            diff_label = {'easy': 'Chill 🐢', 'normal': 'Balanced ⚡', 'hard': 'Pro 🔥'}.get(difficulty, 'Balanced ⚡')
            bot_name = f"🤖 SpitBot ({diff_label})"
            self.players[bot_sid] = {'role': 'p2', 'name': bot_name}
            self.log_event(f"{bot_name} entered the room!")

    def remove_bot(self):
        with self.lock:
            bot_sid = f"bot_{self.room_id}"
            self.is_bot_p2 = False
            if self.p2_sid == bot_sid:
                self.p2_sid = None
                self.players.pop(bot_sid, None)
                self.log_event("SpitBot left the room.")

    def trigger_bot_worker(self):
        if not self.is_bot_p2:
            return

        current_round = self.game_round_id

        def bot_worker():
            bot_sid = f"bot_{self.room_id}"
            while True:
                # Balanced human-like pacing
                if self.bot_difficulty == 'easy':
                    delay = random.uniform(2.5, 3.8)
                    hesitation_chance = 0.20
                    slap_delay = random.uniform(0.8, 1.4)
                elif self.bot_difficulty == 'hard':
                    delay = random.uniform(0.9, 1.5)
                    hesitation_chance = 0.05
                    slap_delay = random.uniform(0.3, 0.6)
                else:  # normal / balanced
                    delay = random.uniform(1.6, 2.6)
                    hesitation_chance = 0.10
                    slap_delay = random.uniform(0.5, 0.9)

                socketio.sleep(delay)

                with self.lock:
                    if self.status != 'playing' or not self.is_bot_p2 or self.p2_sid != bot_sid or self.game_round_id != current_round:
                        break

                    # 1. Slap handling
                    if self.can_slap:
                        # Human-like reaction time
                        socketio.sleep(slap_delay)
                        with self.lock:
                            if self.can_slap and self.status == 'playing' and self.game_round_id == current_round:
                                chosen_pile = 1 if len(self.pile1) <= len(self.pile2) else 2
                                self.apply_slap('p2', chosen_pile)
                                sync_room_state(self)
                        break

                    if not self.pile1 or not self.pile2:
                        continue

                    p1_top = self.pile1[-1]
                    p2_top = self.pile2[-1]

                    # 2. Check moves to center piles from non-empty tableau piles
                    center_moves = []
                    for p_idx, pile in enumerate(self.p2_tableau):
                        if pile and pile[-1].get('face_up'):
                            top_c = pile[-1]
                            if is_valid_spit_move(top_c['rank'], p1_top['rank']):
                                center_moves.append((p_idx, top_c, 1))
                            if is_valid_spit_move(top_c['rank'], p2_top['rank']):
                                center_moves.append((p_idx, top_c, 2))

                    # 3. Check gap fills (move card to empty slot to uncover face-down card)
                    gap_moves = []
                    empty_slots = [j for j, p in enumerate(self.p2_tableau) if len(p) == 0]
                    if empty_slots:
                        # Prioritize moving from piles with face-down cards underneath
                        piles_with_hidden = [i for i, p in enumerate(self.p2_tableau) if len(p) > 1 and not p[-2].get('face_up')]
                        if piles_with_hidden:
                            for source_idx in piles_with_hidden:
                                gap_moves.append((source_idx, self.p2_tableau[source_idx][-1], empty_slots[0]))
                        else:
                            piles_multi = [i for i, p in enumerate(self.p2_tableau) if len(p) > 1]
                            for source_idx in piles_multi:
                                gap_moves.append((source_idx, self.p2_tableau[source_idx][-1], empty_slots[0]))

                    if center_moves:
                        if random.random() >= hesitation_chance:
                            p_idx, card, pile_num = random.choice(center_moves)
                            self.p2_tableau[p_idx].pop()
                            target_pile = self.pile1 if pile_num == 1 else self.pile2
                            target_pile.append(card)

                            # Expose new top card in pile
                            if self.p2_tableau[p_idx]:
                                self.p2_tableau[p_idx][-1]['face_up'] = True

                            self.p1_spit = False
                            self.p2_spit = False
                            bot_name = self.players.get(bot_sid, {}).get('name', '🤖 SpitBot')
                            self.log_event(f"{bot_name} played {card['label']}{card['symbol']} on Pile {pile_num}")

                            # Check if tableau cleared
                            if all(len(p) == 0 for p in self.p2_tableau):
                                self.can_slap = True
                                self.log_event(f"⚡ {bot_name} cleared all 5 tableau piles! RACE TO SLAP A CENTER PILE!")

                    elif gap_moves:
                        source_idx, card, target_idx = gap_moves[0]
                        self.p2_tableau[source_idx].pop()
                        self.p2_tableau[target_idx].append(card)
                        if self.p2_tableau[source_idx]:
                            self.p2_tableau[source_idx][-1]['face_up'] = True
                        bot_name = self.players.get(bot_sid, {}).get('name', '🤖 SpitBot')
                        self.log_event(f"{bot_name} moved {card['label']}{card['symbol']} to empty tableau slot {target_idx + 1}")
                    else:
                        bot_name = self.players.get(bot_sid, {}).get('name', '🤖 SpitBot')
                        if not self.p2_spit:
                            self.p2_spit = True
                            self.log_event(f"{bot_name} is stuck and called SPIT! (1/2 Ready) Tap SPIT to flip together!")
                        if self.p1_spit and self.p2_spit:
                            self.log_event("💥 Both players called SPIT! Simultaneous flip!")
                            self.spit_flip()

                sync_room_state(self)

        socketio.start_background_task(bot_worker)

    def reset_game(self):
        with self.lock:
            self.game_round_id += 1
            self.round_num = 1
            self.winner = None
            self.can_slap = False
            deck = create_deck()
            p1_cards = deck[:26]
            p2_cards = deck[26:]

            self.p1_tableau, self.p1_spit_stock = deal_tableau_from_cards(p1_cards)
            self.p2_tableau, self.p2_spit_stock = deal_tableau_from_cards(p2_cards)

            c1 = self.p1_spit_stock.pop(0) if self.p1_spit_stock else create_card(random.randint(1, 13), random.choice(SUITS), face_up=True)
            c2 = self.p2_spit_stock.pop(0) if self.p2_spit_stock else create_card(random.randint(1, 13), random.choice(SUITS), face_up=True)
            c1['face_up'] = True
            c2['face_up'] = True
            self.pile1 = [c1]
            self.pile2 = [c2]

            self.p1_spit = False
            self.p2_spit = False
            self.status = 'playing'
            self.start_time = time.time()
            self.log_event('Round 1 started! 5 tableau piles dealt. Central piles seeded.')

    def deal_next_round(self, p1_cards, p2_cards):
        with self.lock:
            self.game_round_id += 1
            self.round_num += 1
            self.can_slap = False
            random.shuffle(p1_cards)
            random.shuffle(p2_cards)

            self.p1_tableau, self.p1_spit_stock = deal_tableau_from_cards(p1_cards)
            self.p2_tableau, self.p2_spit_stock = deal_tableau_from_cards(p2_cards)

            c1 = None
            if self.p1_spit_stock:
                c1 = self.p1_spit_stock.pop(0)
            elif self.p2_spit_stock:
                c1 = self.p2_spit_stock.pop(0)
            else:
                c1 = create_card(random.randint(1, 13), random.choice(SUITS))

            c2 = None
            if self.p2_spit_stock:
                c2 = self.p2_spit_stock.pop(0)
            elif self.p1_spit_stock:
                c2 = self.p1_spit_stock.pop(0)
            else:
                c2 = create_card(random.randint(1, 13), random.choice(SUITS))

            c1['face_up'] = True
            c2['face_up'] = True
            self.pile1 = [c1]
            self.pile2 = [c2]

            self.p1_spit = False
            self.p2_spit = False
            self.status = 'playing'
            self.log_event(f'Round {self.round_num} dealt! (P1: {len(p1_cards)} cards, P2: {len(p2_cards)} cards)')

        if self.is_bot_p2:
            self.trigger_bot_worker()

    def apply_slap(self, slapping_role, chosen_pile_num):
        with self.lock:
            if not self.can_slap or self.status != 'playing':
                return False

            slapper_info = self.players.get(self.p1_sid if slapping_role == 'p1' else self.p2_sid, {})
            slapper_name = slapper_info.get('name', 'Player 1' if slapping_role == 'p1' else 'Player 2')

            chosen_pile = list(self.pile1) if chosen_pile_num == 1 else list(self.pile2)
            other_pile = list(self.pile2) if chosen_pile_num == 1 else list(self.pile1)

            p1_collected = []
            p2_collected = []

            if slapping_role == 'p1':
                p1_collected.extend(chosen_pile)
                p2_collected.extend(other_pile)
            else:
                p2_collected.extend(chosen_pile)
                p1_collected.extend(other_pile)

            for p in self.p1_tableau:
                p1_collected.extend(p)
            p1_collected.extend(self.p1_spit_stock)

            for p in self.p2_tableau:
                p2_collected.extend(p)
            p2_collected.extend(self.p2_spit_stock)

            # Check Game Over
            if len(p1_collected) == 0:
                self.status = 'game_over'
                self.winner = 'p1'
                self.can_slap = False
                self.match_duration = int(time.time() - self.start_time) if self.start_time else 0
                p1_name = self.players.get(self.p1_sid, {}).get('name', 'Player 1')
                self.log_event(f"🏆 {p1_name} shed all cards and won the match in {self.match_duration}s!")
                return True
            elif len(p2_collected) == 0:
                self.status = 'game_over'
                self.winner = 'p2'
                self.can_slap = False
                self.match_duration = int(time.time() - self.start_time) if self.start_time else 0
                p2_name = self.players.get(self.p2_sid, {}).get('name', 'Player 2')
                self.log_event(f"🏆 {p2_name} shed all cards and won the match in {self.match_duration}s!")
                return True

            self.log_event(f"⚡ {slapper_name} slapped Pile {chosen_pile_num} ({len(chosen_pile)} cards)! Opponent took {len(other_pile)} cards.")
            self.deal_next_round(p1_collected, p2_collected)
            return True

    def spit_flip(self):
        """Flips 1 card to Pile 1 and 1 card to Pile 2 when stuck"""
        with self.lock:
            # 1. If both stocks empty, recycle underneath cards from center piles
            if not self.p1_spit_stock and not self.p2_spit_stock:
                recycled = []
                if len(self.pile1) > 1:
                    recycled.extend(self.pile1[:-1])
                    self.pile1 = [self.pile1[-1]]
                if len(self.pile2) > 1:
                    recycled.extend(self.pile2[:-1])
                    self.pile2 = [self.pile2[-1]]

                if recycled:
                    random.shuffle(recycled)
                    half = len(recycled) // 2
                    self.p1_spit_stock.extend(recycled[:half])
                    self.p2_spit_stock.extend(recycled[half:])
                    self.log_event(f"Recycled {len(recycled)} cards from center piles into spit stocks!")

            # 2. Draw card for Pile 1
            c1 = None
            if self.p1_spit_stock:
                c1 = self.p1_spit_stock.pop(0)
            elif self.p2_spit_stock:
                c1 = self.p2_spit_stock.pop(0)

            # 3. Draw card for Pile 2
            c2 = None
            if self.p2_spit_stock:
                c2 = self.p2_spit_stock.pop(0)
            elif self.p1_spit_stock:
                c2 = self.p1_spit_stock.pop(0)

            # 4. Fallback if stocks & piles are completely exhausted
            if not c1 or not c2:
                all_cards = []
                for p in self.p1_tableau: all_cards.extend(p)
                for p in self.p2_tableau: all_cards.extend(p)
                all_cards.extend(self.pile1 + self.pile2 + self.p1_spit_stock + self.p2_spit_stock)
                used_ids = {c['id'] for c in all_cards if c}
                fresh_cards = [c for c in create_deck() if c['id'] not in used_ids]
                random.shuffle(fresh_cards)
                if not c1 and fresh_cards:
                    c1 = fresh_cards.pop(0)
                if not c2 and fresh_cards:
                    c2 = fresh_cards.pop(0)

            if c1:
                c1['face_up'] = True
                self.pile1.append(c1)
            if c2:
                c2['face_up'] = True
                self.pile2.append(c2)

            self.p1_spit = False
            self.p2_spit = False
            c1_text = f"{c1['label']}{c1['symbol']}" if c1 else "None"
            c2_text = f"{c2['label']}{c2['symbol']}" if c2 else "None"
            self.log_event(f'SPIT! Flipped {c1_text} onto Pile 1, {c2_text} onto Pile 2')

    def get_state_for_player(self, sid):
        with self.lock:
            player_info = self.players.get(sid, {})
            role = player_info.get('role', 'spectator')

            p1_name = self.players.get(self.p1_sid, {}).get('name', 'Player 1') if self.p1_sid else 'Player 1'
            p2_name = self.players.get(self.p2_sid, {}).get('name', 'Player 2') if self.p2_sid else 'Player 2'

            p1_tab_count = sum(len(p) for p in self.p1_tableau)
            p1_stock_count = len(self.p1_spit_stock)
            p1_total = p1_tab_count + p1_stock_count

            p2_tab_count = sum(len(p) for p in self.p2_tableau)
            p2_stock_count = len(self.p2_spit_stock)
            p2_total = p2_tab_count + p2_stock_count

            def sanitize_tableau_for_opp(tableau):
                # Anti-cheat / Privacy: hide rank and suit for face-down cards
                sanitized = []
                for pile in tableau:
                    san_pile = []
                    for c in pile:
                        if c.get('face_up'):
                            san_pile.append(c)
                        else:
                            san_pile.append({'id': 'hidden', 'face_up': False})
                    sanitized.append(san_pile)
                return sanitized

            if role == 'p1':
                your_tableau = self.p1_tableau
                your_stock = p1_stock_count
                your_total = p1_total
                opp_tableau = sanitize_tableau_for_opp(self.p2_tableau)
                opp_stock = p2_stock_count
                opp_total = p2_total
                your_spit = self.p1_spit
                opp_spit = self.p2_spit
            elif role == 'p2':
                your_tableau = self.p2_tableau
                your_stock = p2_stock_count
                your_total = p2_total
                opp_tableau = sanitize_tableau_for_opp(self.p1_tableau)
                opp_stock = p1_stock_count
                opp_total = p1_total
                your_spit = self.p2_spit
                opp_spit = self.p1_spit
            else:
                your_tableau = sanitize_tableau_for_opp(self.p1_tableau)
                your_stock = p1_stock_count
                your_total = p1_total
                opp_tableau = sanitize_tableau_for_opp(self.p2_tableau)
                opp_stock = p2_stock_count
                opp_total = p2_total
                your_spit = False
                opp_spit = False

            # Top cards for backward compatibility
            your_hand = [p[-1] for p in your_tableau if p and p[-1].get('face_up')]
            opp_hand = [p[-1] for p in opp_tableau if p and p[-1].get('face_up')]

            return {
                'room_id': self.room_id,
                'status': self.status,
                'role': role,
                'round_num': self.round_num,
                'p1_name': p1_name,
                'p2_name': p2_name,
                'p1_connected': self.p1_sid is not None,
                'p2_connected': self.p2_sid is not None,
                'is_bot': self.is_bot_p2,
                'bot_difficulty': self.bot_difficulty,
                'pile1_top': self.pile1[-1] if self.pile1 else None,
                'pile2_top': self.pile2[-1] if self.pile2 else None,
                'pile1_count': len(self.pile1),
                'pile2_count': len(self.pile2),
                'your_tableau': your_tableau,
                'your_hand': your_hand,
                'your_stock_count': your_stock,
                'your_total_cards': your_total,
                'opponent_tableau': opp_tableau,
                'opponent_hand': opp_hand,
                'opponent_stock_count': opp_stock,
                'opponent_total_cards': opp_total,
                'can_slap': self.can_slap,
                'your_spit': your_spit,
                'opp_spit': opp_spit,
                'winner': self.winner,
                'countdown': self.countdown_val,
                'match_duration': self.match_duration or (int(time.time() - self.start_time) if self.start_time else 0),
                'log': self.log[-6:]
            }

def get_or_create_room(room_id) -> GameRoom:
    with rooms_lock:
        if room_id not in rooms:
            rooms[room_id] = GameRoom(room_id)
        return rooms[room_id]

def _find_room_for_sid(room_id, sid):
    """Resilient room resolver using explicit room ID or player SID"""
    if room_id and room_id in rooms:
        return rooms[room_id]
    for r_id, r in rooms.items():
        if sid in r.players or r.p1_sid == sid or r.p2_sid == sid:
            return r
    return None

import socket

def get_local_ip() -> str:
    """Detects the host machine's local LAN IPv4 address for multi-device network play."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --- Routes ---
@app.route('/')
def index():
    local_ip = get_local_ip()
    port = int(os.environ.get('PORT', 5000))
    return render_template('index.html', local_ip=local_ip, port=port)

@app.route('/favicon.ico')
def favicon():
    return ('', 204)


# --- WebSocket Event Handlers ---
def get_request_sid() -> str:
    """Safely retrieves socket session ID injected into request context by Flask-SocketIO"""
    return getattr(request, 'sid', '')

def clean_player_from_other_rooms(sid: str, except_room_id: str = None):
    """Ensures a client session only exists in one room at a time, preventing cross-room state conflicts."""
    if not sid:
        return
    with rooms_lock:
        for r_id, r in list(rooms.items()):
            if r_id != except_room_id:
                with r.lock:
                    if sid in r.players:
                        r.players.pop(sid, None)
                        if r.p1_sid == sid:
                            r.p1_sid = None
                            if r.is_bot_p2:
                                r.remove_bot()
                        elif r.p2_sid == sid:
                            r.p2_sid = None
                        try:
                            leave_room(r_id, sid=sid)
                        except Exception:
                            pass
                        sync_room_state(r)

@socketio.on('create_room')
def on_create_room(data):
    sid = get_request_sid()
    player_name = str(data.get('name') or 'Player 1').strip()
    with rooms_lock:
        for _ in range(100):
            code = f"{random.randint(100000, 999999)}"
            if code not in rooms:
                break
        else:
            code = str(uuid.uuid4())[:6]
        room = get_or_create_room(code)

    clean_player_from_other_rooms(sid, except_room_id=code)

    with room.lock:
        join_room(code)
        room.p1_sid = sid
        room.players[sid] = {'role': 'p1', 'name': player_name}
        room.log_event(f'{player_name} created Room {code}.')

    emit('room_created', {'room': code, 'name': player_name})
    sync_room_state(room)

@socketio.on('join_game')
def on_join(data):
    sid = get_request_sid()
    room_id = str(data.get('room') or '').strip()
    player_name = str(data.get('name') or '').strip()
    join_only = bool(data.get('join_only', False))

    if not room_id:
        room_id = 'lobby'

    clean_player_from_other_rooms(sid, except_room_id=room_id)

    with rooms_lock:
        room_exists = room_id in rooms
        if join_only and not room_exists:
            emit('join_error', {
                'message': f'Room code "{room_id}" not found. Please verify the 6-digit code with your host!'
            })
            return
        room = get_or_create_room(room_id)

    ready_to_start = False
    with room.lock:
        # Check if room is full for a new player joining
        if sid != room.p1_sid and sid != room.p2_sid:
            if room.p1_sid is not None and room.p2_sid is not None and not room.is_bot_p2:
                if join_only:
                    emit('join_error', {
                        'message': f'Room "{room_id}" is already full with 2 active players!'
                    })
                    return
                # Non-join_only fallback: join as spectator
                if not player_name:
                    player_name = f'Spectator {len(room.players)+1}'
                join_room(room_id)
                room.players[sid] = {'role': 'spectator', 'name': player_name}
                room.log_event(f'{player_name} joined as Spectator.')
                sync_room_state(room)
                return

        join_room(room_id)
        if room.p1_sid is None:
            room.p1_sid = sid
            if not player_name:
                player_name = 'Player 1'
            room.players[sid] = {'role': 'p1', 'name': player_name}
            room.log_event(f'{player_name} joined as Player 1 (Host).')
        elif room.p2_sid is None or room.is_bot_p2:
            if sid != room.p1_sid:
                if room.is_bot_p2:
                    room.remove_bot()
                room.p2_sid = sid
                if not player_name or player_name == 'Player 1':
                    player_name = 'Player 2'
                room.players[sid] = {'role': 'p2', 'name': player_name}
                room.log_event(f'{player_name} joined as Player 2.')
        else:
            # Reconnecting player updating name
            if sid in room.players and player_name:
                room.players[sid]['name'] = player_name

        ready_to_start = (room.p1_sid is not None and room.p2_sid is not None and room.status in ('waiting', 'game_over'))
        print(f"[DEBUG on_join] sid={sid} room_id={room_id} join_only={join_only} p1={room.p1_sid} p2={room.p2_sid} ready={ready_to_start}")

    if ready_to_start:
        start_countdown(room)
    else:
        sync_room_state(room)

def start_countdown(room):
    def countdown_thread():
        with room.lock:
            room.status = 'countdown'
            room.reset_game()
            room.status = 'countdown'
            room.countdown_val = 3

        # Immediate broadcast of countdown start so clients react with zero delay
        sync_room_state(room)
        socketio.sleep(1.0)

        for count in [2, 1]:
            with room.lock:
                room.countdown_val = count
            sync_room_state(room)
            socketio.sleep(1.0)

        with room.lock:
            room.countdown_val = 0
            room.status = 'playing'
            room.start_time = time.time()
            room.match_duration = 0
            room.log_event('Match started! Fast hands win!')
            room.trigger_bot_worker()
        sync_room_state(room)

    socketio.start_background_task(countdown_thread)

def sync_room_state(room):
    with app.app_context():
        for sid in list(room.players.keys()):
            if sid.startswith('bot_'):
                continue
            state = room.get_state_for_player(sid)
            socketio.emit('game_state', state, to=sid)

@socketio.on('start_bot_game')
def on_start_bot_game(data):
    sid = get_request_sid()
    room_id = (data.get('room') or 'lobby').strip()
    difficulty = data.get('difficulty', 'normal')
    player_name = (data.get('name') or 'Player 1').strip()
    room = get_or_create_room(room_id)
    with room.lock:
        join_room(room_id)
        room.p1_sid = sid
        room.players[sid] = {'role': 'p1', 'name': player_name}
        room.add_bot(difficulty)
        room.log_event(f'{player_name} initiated solo clash vs SpitBot ({difficulty.title()})!')
    start_countdown(room)

@socketio.on('add_bot')
def on_add_bot(data):
    room_id = (data.get('room') or 'lobby').strip()
    difficulty = data.get('difficulty', 'normal')
    room = get_or_create_room(room_id)
    with room.lock:
        room.add_bot(difficulty)
    start_countdown(room)

@socketio.on('remove_bot')
def on_remove_bot(data):
    room_id = (data.get('room') or 'lobby').strip()
    if room_id in rooms:
        room = rooms[room_id]
        with room.lock:
            room.remove_bot()
            room.status = 'waiting'
        sync_room_state(room)

@socketio.on('reset_to_waiting')
def on_reset_to_waiting(data):
    room_id = (data.get('room') or 'lobby').strip()
    if room_id in rooms:
        room = rooms[room_id]
        with room.lock:
            room.remove_bot()
            room.status = 'waiting'
            room.p1_spit = False
            room.p2_spit = False
            room.winner = None
            room.log_event('Match reset to mode selection lobby.')
        sync_room_state(room)


@socketio.on('play_card')
def on_play_card(data):
    sid = get_request_sid()
    room_id = (data.get('room') or '').strip()
    card_id = data.get('card_id')
    target = data.get('target', 'center')  # 'center' or 'tableau'
    pile_num = int(data.get('pile', 1))
    from_pile = data.get('from_pile')  # 0..4 (optional)
    to_pile = data.get('to_pile')  # 0..4 (for empty pile gap fill)

    room = _find_room_for_sid(room_id, sid)
    if not room:
        emit('invalid_move', {'reason': 'Game room not found. Please refresh.'})
        return

    with room.lock:
        if room.status != 'playing':
            emit('invalid_move', {'reason': 'Game is not in playing state'})
            return

        player_info = room.players.get(sid)
        if not player_info:
            if room.p1_sid == sid:
                player_info = {'role': 'p1', 'name': 'Player 1'}
                room.players[sid] = player_info
            elif room.p2_sid == sid:
                player_info = {'role': 'p2', 'name': 'Player 2'}
                room.players[sid] = player_info
            else:
                emit('invalid_move', {'reason': 'Only active players can move cards'})
                return

        role = player_info['role']
        if role not in ('p1', 'p2'):
            emit('invalid_move', {'reason': 'Only active players can move cards'})
            return

        player_tableau = room.p1_tableau if role == 'p1' else room.p2_tableau
        player_name = player_info['name']

        # Find from_pile if not explicitly provided
        src_pile_idx = -1
        target_card = None
        if from_pile is not None and 0 <= int(from_pile) < 5:
            p = player_tableau[int(from_pile)]
            if p and p[-1].get('face_up') and (card_id is None or p[-1]['id'] == card_id):
                src_pile_idx = int(from_pile)
                target_card = p[-1]

        if target_card is None:
            for idx, p in enumerate(player_tableau):
                if p and p[-1].get('face_up') and p[-1]['id'] == card_id:
                    src_pile_idx = idx
                    target_card = p[-1]
                    break

        if target_card is None:
            emit('invalid_move', {'card_id': card_id, 'reason': 'Card not available or not on top of your tableau piles'})
            return

        # 1. Gap Fill: move face-up card to empty tableau pile
        if target == 'tableau' or to_pile is not None:
            if to_pile is None or not (0 <= int(to_pile) < 5):
                emit('invalid_move', {'reason': 'Invalid target tableau slot'})
                return
            dest_pile_idx = int(to_pile)
            if len(player_tableau[dest_pile_idx]) > 0:
                emit('invalid_move', {'reason': 'Cards can only be moved into empty tableau slots'})
                return

            player_tableau[src_pile_idx].pop()
            player_tableau[dest_pile_idx].append(target_card)
            if player_tableau[src_pile_idx]:
                player_tableau[src_pile_idx][-1]['face_up'] = True

            room.p1_spit = False
            room.p2_spit = False
            room.log_event(f"{player_name} moved {target_card['label']}{target_card['symbol']} to empty tableau slot {dest_pile_idx + 1}")
            sync_room_state(room)
            return

        # 2. Play to Center Pile (1 or 2)
        target_center_pile = room.pile1 if pile_num == 1 else room.pile2
        if not target_center_pile:
            emit('invalid_move', {'card_id': card_id, 'reason': 'Target pile is empty'})
            return

        top_center = target_center_pile[-1]
        if not is_valid_spit_move(target_card['rank'], top_center['rank']):
            emit('invalid_move', {
                'card_id': card_id,
                'pile': pile_num,
                'reason': f"{target_card['label']}{target_card['symbol']} cannot play on {top_center['label']}{top_center['symbol']}! Must be +/- 1 rank (Ace wraps King & 2)."
            })
            return

        player_tableau[src_pile_idx].pop()
        target_center_pile.append(target_card)
        if player_tableau[src_pile_idx]:
            player_tableau[src_pile_idx][-1]['face_up'] = True

        room.p1_spit = False
        room.p2_spit = False
        room.log_event(f"{player_name} played {target_card['label']}{target_card['symbol']} on Pile {pile_num}")

        # Check if tableau cleared -> triggers SLAP RACE!
        if all(len(p) == 0 for p in player_tableau):
            room.can_slap = True
            room.log_event(f"⚡ {player_name} cleared all 5 tableau piles! RACE TO SLAP A CENTER PILE!")

    sync_room_state(room)

@socketio.on('slap')
def on_slap(data):
    sid = get_request_sid()
    room_id = (data.get('room') or '').strip()
    pile_num = int(data.get('pile', 1))
    if pile_num not in (1, 2):
        pile_num = 1

    room = _find_room_for_sid(room_id, sid)
    if not room:
        return

    with room.lock:
        if not room.can_slap or room.status != 'playing':
            return
        player_info = room.players.get(sid)
        if not player_info or player_info.get('role') not in ('p1', 'p2'):
            return
        role = player_info['role']
        room.apply_slap(role, pile_num)

    sync_room_state(room)

@socketio.on('request_spit')
def on_request_spit(data):
    sid = get_request_sid()
    room_id = (data.get('room') or '').strip()
    room = _find_room_for_sid(room_id, sid)
    if not room:
        return

    flip_now = False
    with room.lock:
        if room.status != 'playing':
            return
        player_info = room.players.get(sid)
        if not player_info or player_info['role'] not in ('p1', 'p2'):
            return

        role = player_info['role']
        player_name = player_info['name']

        if role == 'p1':
            room.p1_spit = True
            room.log_event(f"{player_name} called SPIT! (1/2 Ready)")

            if room.is_bot_p2:
                if room.p2_spit:
                    room.log_event("💥 Both players called SPIT! Simultaneous flip!")
                    flip_now = True
                else:
                    # Check if bot has any valid moves
                    p1_top = room.pile1[-1] if room.pile1 else None
                    p2_top = room.pile2[-1] if room.pile2 else None
                    bot_has_moves = False
                    if p1_top and p2_top:
                        for p in room.p2_tableau:
                            if p and p[-1].get('face_up'):
                                top_c = p[-1]
                                if is_valid_spit_move(top_c['rank'], p1_top['rank']) or is_valid_spit_move(top_c['rank'], p2_top['rank']):
                                    bot_has_moves = True
                                    break

                    bot_sid = f"bot_{room.room_id}"
                    bot_name = room.players.get(bot_sid, {}).get('name', '🤖 SpitBot')
                    if not bot_has_moves:
                        room.p2_spit = True
                        room.log_event(f"{bot_name} is also stuck and called SPIT!")
                        room.log_event("💥 Both players called SPIT! Simultaneous flip!")
                        flip_now = True
                    else:
                        room.log_event(f"{bot_name}: I still have a playable card! Not stuck yet.")
            else:
                if room.p1_spit and room.p2_spit:
                    room.log_event("💥 Both players called SPIT! Simultaneous flip!")
                    flip_now = True
                else:
                    room.log_event("Waiting for Player 2 to tap SPIT...")

        elif role == 'p2':
            room.p2_spit = True
            room.log_event(f"{player_name} called SPIT! (1/2 Ready)")
            if room.p1_spit and room.p2_spit:
                room.log_event("💥 Both players called SPIT! Simultaneous flip!")
                flip_now = True
            else:
                room.log_event("Waiting for Player 1 to tap SPIT...")

    if flip_now:
        room.spit_flip()

    sync_room_state(room)

@socketio.on('set_bot_difficulty')
def on_set_bot_difficulty(data):
    room_id = (data.get('room') or 'lobby').strip()
    diff = data.get('difficulty', 'normal')
    if diff not in ('easy', 'normal', 'hard'):
        diff = 'normal'
    room = get_or_create_room(room_id)
    with room.lock:
        if room.is_bot_p2:
            room.bot_difficulty = diff
            diff_label = {'easy': 'Chill 🐢', 'normal': 'Balanced ⚡', 'hard': 'Pro 🔥'}.get(diff, 'Balanced ⚡')
            bot_name = f"🤖 SpitBot ({diff_label})"
            bot_sid = f"bot_{room.room_id}"
            room.players[bot_sid] = {'role': 'p2', 'name': bot_name}
            room.log_event(f"SpitBot speed changed to {diff_label}!")
    sync_room_state(room)

@socketio.on('rematch')
def on_rematch(data):
    room_id = (data.get('room') or '').strip()
    room = None
    sid = get_request_sid()
    if room_id and room_id in rooms:
        room = rooms[room_id]
    else:
        for r_id, r in rooms.items():
            if sid in r.players:
                room_id = r_id
                room = r
                break
    if not room:
        return

    can_start = False
    with room.lock:
        if room.p1_sid is not None and (room.p2_sid is not None or room.is_bot_p2):
            can_start = True
    if can_start:
        start_countdown(room)

@socketio.on('disconnect')
def on_disconnect():
    sid = get_request_sid()
    for room_id, room in list(rooms.items()):
        with room.lock:
            if sid in room.players:
                player_info = room.players.pop(sid)
                name = player_info.get('name', 'A player')
                role = player_info.get('role')

                if room.p1_sid == sid:
                    room.p1_sid = None
                    if room.is_bot_p2:
                        room.remove_bot()
                elif room.p2_sid == sid:
                    room.p2_sid = None

                room.log_event(f'{name} ({role}) disconnected.')
                if room.status == 'playing':
                    room.status = 'waiting'
                    room.log_event('Game halted: waiting for players.')

                sync_room_state(room)

    # Clean up empty non-lobby rooms to prevent memory leaks
    with rooms_lock:
        for r_id in list(rooms.keys()):
            if r_id != 'lobby' and r_id in rooms:
                r = rooms[r_id]
                with r.lock:
                    human_count = sum(1 for s in r.players if not s.startswith('bot_'))
                    if r.p1_sid is None and r.p2_sid is None and human_count == 0:
                        del rooms[r_id]

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Starting Spit Game Server on http://0.0.0.0:{port}...')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
