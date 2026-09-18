import unittest
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

class TestSpitRules(unittest.TestCase):
    def test_deal_tableau_26_cards(self):
        deck = create_deck()
        p1_cards = deck[:26]
        tableau, spit_stock = deal_tableau_from_cards(p1_cards)
        
        self.assertEqual(len(tableau), 5)
        self.assertEqual([len(p) for p in tableau], [1, 2, 3, 4, 5])
        self.assertEqual(sum(len(p) for p in tableau), 15)
        self.assertEqual(len(spit_stock), 11)
        
        for p in tableau:
            self.assertTrue(p[-1]['face_up'])
            for c in p[:-1]:
                self.assertFalse(c['face_up'])

    def test_deal_tableau_fewer_cards(self):
        deck = create_deck()
        small_pool = deck[:8]
        tableau, spit_stock = deal_tableau_from_cards(small_pool)
        total_in_tab = sum(len(p) for p in tableau)
        self.assertEqual(total_in_tab, 8)
        self.assertEqual(len(spit_stock), 0)
        for p in tableau:
            if p:
                self.assertTrue(p[-1]['face_up'])

    def test_move_to_center_and_auto_flip(self):
        tableau = [
            [create_card(7, 'hearts', face_up=True)],
            [create_card(5, 'spades', face_up=False), create_card(8, 'clubs', face_up=True)],
            [], [], []
        ]
        pile1 = [create_card(9, 'diamonds', face_up=True)]
        
        card_to_play = tableau[1][-1]
        self.assertTrue(is_valid_spit_move(card_to_play['rank'], pile1[-1]['rank']))
        
        tableau[1].pop()
        pile1.append(card_to_play)
        if tableau[1]:
            tableau[1][-1]['face_up'] = True
            
        self.assertEqual(len(tableau[1]), 1)
        self.assertTrue(tableau[1][-1]['face_up'])
        self.assertEqual(tableau[1][-1]['rank'], 5)

    def test_gap_fill(self):
        tableau = [
            [], # empty pile
            [create_card(4, 'hearts', face_up=False), create_card(10, 'spades', face_up=True)],
            [], [], []
        ]
        card = tableau[1].pop()
        tableau[0].append(card)
        if tableau[1]:
            tableau[1][-1]['face_up'] = True
            
        self.assertEqual(len(tableau[0]), 1)
        self.assertEqual(tableau[0][0]['rank'], 10)
        self.assertTrue(tableau[0][0]['face_up'])
        self.assertEqual(len(tableau[1]), 1)
        self.assertTrue(tableau[1][0]['face_up'])
        self.assertEqual(tableau[1][0]['rank'], 4)

    def test_wrap_rules(self):
        self.assertTrue(is_valid_spit_move(1, 13))
        self.assertTrue(is_valid_spit_move(13, 1))
        self.assertTrue(is_valid_spit_move(2, 1))
        self.assertTrue(is_valid_spit_move(1, 2))
        self.assertFalse(is_valid_spit_move(5, 5))
        self.assertFalse(is_valid_spit_move(3, 5))

if __name__ == '__main__':
    unittest.main()
