import unittest
import time
import random
import uuid
import threading

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
    diff = (card_rank - target_top_rank) % 13
    return diff in (1, 12)

def deal_tableau_from_cards(cards):
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

class FullGameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.lock = threading.RLock()
        self.p1_sid = 'p1_session'
        self.p2_sid = 'p2_session'
        self.is_bot_p2 = False
        self.bot_difficulty = 'normal'
        self.players = {
            'p1_session': {'role': 'p1', 'name': 'Player 1'},
            'p2_session': {'role': 'p2', 'name': 'Player 2'}
        }
        self.status = 'waiting'
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
        self.start_time = time.time()
        self.match_duration = 0
        self.game_round_id = 0
        self.log = []

    def log_event(self, msg):
        self.log.append(msg)

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
            self.log_event(f'Round {self.round_num} dealt! (P1: {len(p1_cards)}, P2: {len(p2_cards)})')

    def apply_slap(self, slapping_role, chosen_pile_num):
        with self.lock:
            if not self.can_slap or self.status != 'playing':
                return False

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

            if len(p1_collected) == 0:
                self.status = 'game_over'
                self.winner = 'p1'
                self.can_slap = False
                return True
            elif len(p2_collected) == 0:
                self.status = 'game_over'
                self.winner = 'p2'
                self.can_slap = False
                return True

            self.deal_next_round(p1_collected, p2_collected)
            return True

    def get_state_for_player(self, sid):
        with self.lock:
            player_info = self.players.get(sid, {})
            role = player_info.get('role', 'spectator')

            p1_tab_count = sum(len(p) for p in self.p1_tableau)
            p1_stock_count = len(self.p1_spit_stock)
            p1_total = p1_tab_count + p1_stock_count

            p2_tab_count = sum(len(p) for p in self.p2_tableau)
            p2_stock_count = len(self.p2_spit_stock)
            p2_total = p2_tab_count + p2_stock_count

            def sanitize_tableau_for_opp(tableau):
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
            else:
                your_tableau = self.p2_tableau
                your_stock = p2_stock_count
                your_total = p2_total
                opp_tableau = sanitize_tableau_for_opp(self.p1_tableau)
                opp_stock = p1_stock_count
                opp_total = p1_total

            return {
                'role': role,
                'round_num': self.round_num,
                'pile1_count': len(self.pile1),
                'pile2_count': len(self.pile2),
                'your_tableau': your_tableau,
                'your_stock_count': your_stock,
                'your_total_cards': your_total,
                'opponent_tableau': opp_tableau,
                'opponent_stock_count': opp_stock,
                'opponent_total_cards': opp_total,
                'can_slap': self.can_slap,
                'winner': self.winner,
                'status': self.status
            }

class TestFullGameRoom(unittest.TestCase):
    def test_state_sanitization(self):
        room = FullGameRoom('test')
        room.reset_game()
        state_p1 = room.get_state_for_player('p1_session')
        
        # In P1's view, opponent's face-down cards must have 'id': 'hidden' and no 'rank'/'suit'
        opp_tab = state_p1['opponent_tableau']
        for pile in opp_tab:
            for card in pile[:-1]:
                self.assertFalse(card.get('face_up'))
                self.assertEqual(card.get('id'), 'hidden')
                self.assertNotIn('rank', card)
                self.assertNotIn('suit', card)
            if pile:
                self.assertTrue(pile[-1].get('face_up'))
                self.assertIn('rank', pile[-1])

    def test_play_card_and_slap(self):
        room = FullGameRoom('test')
        room.reset_game()
        # Simulate P1 playing all cards from tableau
        room.p1_tableau = [[], [], [], [], []]
        room.can_slap = True
        
        # P1 slaps pile 1
        res = room.apply_slap('p1', 1)
        self.assertTrue(res)
        self.assertEqual(room.round_num, 2)
        self.assertEqual(room.status, 'playing')

if __name__ == '__main__':
    unittest.main()
