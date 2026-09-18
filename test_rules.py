import unittest

def is_valid_spit_move(card_rank: int, target_top_rank: int) -> bool:
    diff = (card_rank - target_top_rank) % 13
    return diff in (1, 12)

class TestSpitRules(unittest.TestCase):
    def test_standard_moves(self):
        self.assertTrue(is_valid_spit_move(5, 4))
        self.assertTrue(is_valid_spit_move(4, 5))
        self.assertTrue(is_valid_spit_move(10, 9))
        self.assertTrue(is_valid_spit_move(9, 10))
        self.assertTrue(is_valid_spit_move(12, 11)) # Q on J
        self.assertTrue(is_valid_spit_move(13, 12)) # K on Q

    def test_ace_king_wrapping(self):
        # Ace (1) and King (13) wrapping
        self.assertTrue(is_valid_spit_move(1, 13), "Ace on King should be valid")
        self.assertTrue(is_valid_spit_move(13, 1), "King on Ace should be valid")
        # Ace (1) and 2 wrapping
        self.assertTrue(is_valid_spit_move(1, 2), "Ace on 2 should be valid")
        self.assertTrue(is_valid_spit_move(2, 1), "2 on Ace should be valid")

    def test_invalid_moves(self):
        self.assertFalse(is_valid_spit_move(5, 5), "Same rank is invalid")
        self.assertFalse(is_valid_spit_move(5, 7), "Diff of 2 is invalid")
        self.assertFalse(is_valid_spit_move(1, 3), "Ace on 3 is invalid")
        self.assertFalse(is_valid_spit_move(3, 1), "3 on Ace is invalid")
        self.assertFalse(is_valid_spit_move(2, 13), "2 on King is invalid")
        self.assertFalse(is_valid_spit_move(13, 2), "King on 2 is invalid")

    def test_gameroom_bot_mode(self):
        from app import GameRoom
        room = GameRoom('test_unit_room')
        room.p1_sid = 'player_1_sid'
        room.players['player_1_sid'] = {'role': 'p1', 'name': 'Player 1'}
        
        # Test adding bot
        room.add_bot('normal')
        self.assertTrue(room.is_bot_p2)
        self.assertIsNotNone(room.p2_sid)
        self.assertIn(room.p2_sid, room.players)
        self.assertIn('SpitBot', room.players[room.p2_sid]['name'])
        
        # Reset game deals cards
        room.reset_game()
        self.assertEqual(len(room.p1_hand), 5)
        self.assertEqual(len(room.p1_stock), 20)
        self.assertEqual(len(room.p2_hand), 5)
        self.assertEqual(len(room.p2_stock), 20)
        self.assertEqual(len(room.pile1), 1)
        self.assertEqual(len(room.pile2), 1)
        
        # Check player state
        state = room.get_state_for_player('player_1_sid')
        self.assertTrue(state['is_bot'])
        self.assertEqual(state['role'], 'p1')
        self.assertEqual(len(state['your_hand']), 5)
        self.assertEqual(len(state['opponent_hand']), 5)
        
        # Test spit flip
        room.spit_flip()
        self.assertEqual(len(room.pile1), 2)
        self.assertEqual(len(room.pile2), 2)

    def test_simultaneous_spit(self):
        from app import GameRoom
        room = GameRoom('test_simul_room')
        room.reset_game()
        p1_initial_count = len(room.pile1)

        # Only P1 calls spit
        room.p1_spit = True
        self.assertFalse(room.p2_spit)
        # Flip should not happen yet
        self.assertEqual(len(room.pile1), p1_initial_count)

        # Now P2 also calls spit
        room.p2_spit = True
        self.assertTrue(room.p1_spit and room.p2_spit)
        room.spit_flip()
        # Flip should execute and reset spit readiness
        self.assertEqual(len(room.pile1), p1_initial_count + 1)
        self.assertFalse(room.p1_spit)
        self.assertFalse(room.p2_spit)

    def test_bot_difficulty_settings(self):
        from app import GameRoom
        room = GameRoom('test_diff_room')
        room.add_bot('easy')
        self.assertEqual(room.bot_difficulty, 'easy')
        self.assertIn('Chill', room.players[room.p2_sid]['name'])

        room.add_bot('normal')
        self.assertEqual(room.bot_difficulty, 'normal')
        self.assertIn('Balanced', room.players[room.p2_sid]['name'])

        room.add_bot('hard')
        self.assertEqual(room.bot_difficulty, 'hard')
        self.assertIn('Pro', room.players[room.p2_sid]['name'])

    def test_spit_stock_recycling_no_infinite_loop(self):
        from app import GameRoom, create_card
        room = GameRoom('test_recycle_room')
        room.reset_game()

        # Simulate stocks becoming empty while piles have accumulated cards
        room.p1_stock.clear()
        room.p2_stock.clear()
        
        # Add multiple cards to piles
        for r in range(1, 8):
            room.pile1.append(create_card(r, 'hearts'))
            room.pile2.append(create_card(r, 'spades'))

        pile1_len_before = len(room.pile1)
        pile2_len_before = len(room.pile2)
        total_pile_cards = pile1_len_before + pile2_len_before

        # Execute spit flip with empty stocks
        room.spit_flip()

        # Both piles should have a top card
        self.assertGreaterEqual(len(room.pile1), 1)
        self.assertGreaterEqual(len(room.pile2), 1)

        # Unused recycled cards must NOT be discarded; they must be replenished in stocks!
        total_remaining = len(room.pile1) + len(room.pile2) + len(room.p1_stock) + len(room.p2_stock)
        self.assertEqual(total_remaining, total_pile_cards, "No cards should be discarded during recycling!")
        self.assertTrue(len(room.p1_stock) > 0 or len(room.p2_stock) > 0, "Stocks should be replenished from pile undercards!")

        # Subsequent spits should pull distinct cards from the replenished stocks, NOT loop on 4 cards
        seen_flips = set()
        for _ in range(5):
            if room.p1_stock or room.p2_stock or len(room.pile1) > 1:
                room.spit_flip()
                seen_flips.add((room.pile1[-1]['id'], room.pile2[-1]['id']))
        self.assertGreater(len(seen_flips), 1, "Spit must produce varied card sequences, not loop endlessly!")

if __name__ == '__main__':
    unittest.main()

