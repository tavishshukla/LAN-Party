import os
import tempfile
import unittest
from unittest.mock import patch

import server
from server import clean_room_name, clean_username


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


if __name__ == "__main__":
    unittest.main()
