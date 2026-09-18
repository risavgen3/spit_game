import unittest
import time
import random
import uuid

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

class MockRoom:
    def __init__(self):
        self.pile1 = []
        self.pile2 = []
        self.p1_tableau = [[], [], [], [], []]
        self.p1_spit_stock = []
        self.p2_tableau = [[], [], [], [], []]
        self.p2_spit_stock = []
        self.can_slap = False
        self.round_num = 1
        self.status = 'playing'
        self.winner = None
        self.log = []

    def log_event(self, msg):
        self.log.append(msg)

    def reset_game(self):
        deck = create_deck()
        p1_cards = deck[:26]
        p2_cards = deck[26:]
        self.p1_tableau, self.p1_spit_stock = deal_tableau_from_cards(p1_cards)
        self.p2_tableau, self.p2_spit_stock = deal_tableau_from_cards(p2_cards)
        self.pile1 = [self.p1_spit_stock.pop(0)]
        self.pile2 = [self.p2_spit_stock.pop(0)]
        self.pile1[0]['face_up'] = True
        self.pile2[0]['face_up'] = True
        self.can_slap = False
        self.round_num = 1
        self.winner = None

    def apply_slap(self, slapping_role, chosen_pile_num):
        if not self.can_slap or self.status != 'playing':
            return False

        chosen_pile = self.pile1 if chosen_pile_num == 1 else self.pile2
        other_pile = self.pile2 if chosen_pile_num == 1 else self.pile1

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

        # Next round
        self.deal_next_round(p1_collected, p2_collected)
        return True

    def deal_next_round(self, p1_cards, p2_cards):
        self.round_num += 1
        self.can_slap = False
        random.shuffle(p1_cards)
        random.shuffle(p2_cards)
        self.p1_tableau, self.p1_spit_stock = deal_tableau_from_cards(p1_cards)
        self.p2_tableau, self.p2_spit_stock = deal_tableau_from_cards(p2_cards)
        
        self.pile1 = [self.p1_spit_stock.pop(0)] if self.p1_spit_stock else [self.p2_spit_stock.pop(0)]
        self.pile2 = [self.p2_spit_stock.pop(0)] if self.p2_spit_stock else [self.p1_spit_stock.pop(0)]
        self.pile1[0]['face_up'] = True
        self.pile2[0]['face_up'] = True

class TestMockRoom(unittest.TestCase):
    def test_init_game(self):
        room = MockRoom()
        room.reset_game()
        self.assertEqual(len(room.pile1), 1)
        self.assertEqual(len(room.pile2), 1)
        self.assertEqual(len(room.p1_spit_stock), 10)
        self.assertEqual(len(room.p2_spit_stock), 10)
        self.assertEqual(sum(len(p) for p in room.p1_tableau), 15)
        self.assertEqual(sum(len(p) for p in room.p2_tableau), 15)

    def test_slap_round_redistribution(self):
        room = MockRoom()
        room.reset_game()
        # Empty P1's tableau to trigger slap
        room.p1_tableau = [[], [], [], [], []]
        room.can_slap = True
        
        # Set up exact 52 cards:
        # P1 has 0 tableau, 10 spit stock.
        # P2 has 15 tableau, 10 spit stock.
        # Pile 1 has 5 cards, Pile 2 has 12 cards. (10 + 15 + 10 + 5 + 12 = 52)
        room.pile1 = [create_card(1, 'hearts', face_up=True) for _ in range(5)]
        room.pile2 = [create_card(2, 'spades', face_up=True) for _ in range(12)]
        
        # P1 slaps Pile 1 (the smaller pile!)
        res = room.apply_slap('p1', 1)
        self.assertTrue(res)
        self.assertEqual(room.round_num, 2)
        
        # Total cards in deck should still be 52
        total_p1 = sum(len(p) for p in room.p1_tableau) + len(room.p1_spit_stock) + 1 # +1 for center pile card
        total_p2 = sum(len(p) for p in room.p2_tableau) + len(room.p2_spit_stock) + 1 # +1 for center pile card
        self.assertEqual(total_p1 + total_p2, 52)

if __name__ == '__main__':
    unittest.main()
