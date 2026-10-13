import os
import tempfile
import unittest
from unittest.mock import patch

import server
from server import clean_room_name, clean_username, compare_guess, load_scores, record_win, poll_summary, ttt_draw, ttt_winner


class ChatInputTests(unittest.TestCase):
    def test_username_trims_spaces_and_keeps_allowed_characters(self):
        self.assertEqual(clean_username("  Tavish_07  "), "Tavish_07")

    def test_username_removes_disallowed_characters(self):
        self.assertEqual(clean_username("hi! there@"), "hithere")

    def test_username_is_limited_to_twenty_characters(self):
        self.assertEqual(clean_username("abcdefghijklmnopqrstuv"), "abcdefghijklmnopqrst")

    def test_empty_username_stays_empty(self):
        self.assertEqual(clean_username(" !!! "), "")

    def test_room_names_are_lowercase(self):
        self.assertEqual(clean_room_name("GameNight"), "gamenight")

    def test_room_names_allow_hyphens_and_underscores(self):
        self.assertEqual(clean_room_name("Game_Night-2"), "game_night-2")

    def test_room_names_remove_spaces_and_symbols(self):
        self.assertEqual(clean_room_name(" Game Room! "), "gameroom")

    def test_room_name_is_limited_to_twenty_four_characters(self):
        self.assertEqual(clean_room_name("abcdefghijklmnopqrstuvwxyz"), "abcdefghijklmnopqrstuvwx")


class ChatHistoryTests(unittest.TestCase):
    def test_history_keeps_latest_ten_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "history.sqlite3")
            with patch.object(server, "HISTORY_DB", database):
                for number in range(12):
                    server.remember("lobby", {
                        "type": "message",
                        "time": "12:00:00",
                        "name": "player",
                        "text": f"message {number}",
                    })

                history = server.load_history("lobby")
                self.assertEqual(len(history), 10)
                self.assertEqual(history[0]["text"], "message 2")
                self.assertEqual(history[-1]["text"], "message 11")

                # Loading from SQLite again returns the same saved history.
                self.assertEqual(server.load_history("lobby"), history)


class GuessingGameTests(unittest.TestCase):
    def test_guess_too_low(self):
        self.assertEqual(compare_guess(50, 12), "low")

    def test_guess_too_high(self):
        self.assertEqual(compare_guess(50, 88), "high")

    def test_correct_guess(self):
        self.assertEqual(compare_guess(50, 50), "correct")


class ScoreboardTests(unittest.TestCase):
    def test_wins_are_saved_and_sorted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "history.sqlite3")
            with patch.object(server, "HISTORY_DB", database):
                record_win("lobby", "Riyaan")
                record_win("lobby", "Tavish")
                record_win("lobby", "Riyaan")
                self.assertEqual(load_scores("lobby"), [("Riyaan", 2), ("Tavish", 1)])
                self.assertEqual(load_scores("other-room"), [])


class TicTacToeTests(unittest.TestCase):
    def test_row_wins(self):
        self.assertEqual(ttt_winner(["X", "X", "X", "O", None, "O", None, None, None]), "X")

    def test_diagonal_wins(self):
        self.assertEqual(ttt_winner(["O", "X", "X", None, "O", None, "X", None, "O"]), "O")

    def test_incomplete_board_has_no_winner(self):
        self.assertIsNone(ttt_winner(["X", "O", None, None, "X", None, "O", None, None]))

    def test_board_shows_square_numbers_for_empty_cells(self):
        board = ttt_draw([None] * 9)
        self.assertIn("1 | 2 | 3", board)
        self.assertIn("7 | 8 | 9", board)


class PollTests(unittest.TestCase):
    def test_poll_summary_counts_votes(self):
        poll = {
            "question": "Which game next?",
            "options": ["Chess", "Mafia", "Trivia"],
            "votes": {"alex": 1, "sam": 1, "lee": 0},
            "creator": "alex",
        }
        summary = poll_summary(poll)
        self.assertIn("Which game next?", summary)
        self.assertIn("1. Chess — 1 vote(s)", summary)
        self.assertIn("2. Mafia — 2 vote(s)", summary)
        self.assertIn("Total votes: 3", summary)


if __name__ == "__main__":
    unittest.main()
