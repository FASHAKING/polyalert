import logging
import tempfile
import unittest
from unittest.mock import Mock, patch

import bot
from storage import SeenStore


class StorageAndCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.store = SeenStore(self.tmp.name)
        self.http = Mock()
        self.log = logging.getLogger("test")

    def test_pause_resume_interval_and_keyword_watch_commands(self):
        self.assertIn("paused", bot.handle_command("pause", [], "/pause", self.store, 300, self.http, self.log).lower())
        self.assertTrue(self.store.is_paused())

        self.assertIn("resumed", bot.handle_command("resume", [], "/resume", self.store, 300, self.http, self.log).lower())
        self.assertFalse(self.store.is_paused())

        self.assertIn("45s", bot.handle_command("interval", ["45"], "/interval 45", self.store, 300, self.http, self.log))
        self.assertEqual(self.store.get_poll_interval(), 45)

        self.assertIn("Added", bot.handle_command("watch", ["world-cup"], "/watch world-cup", self.store, 45, self.http, self.log))
        self.assertEqual(self.store.get_keyword_watches(), ["world-cup"])

        self.assertIn("Removed", bot.handle_command("unwatch", ["world-cup"], "/unwatch world-cup", self.store, 45, self.http, self.log))
        self.assertEqual(self.store.get_keyword_watches(), [])

    def test_search_command_accepts_soccer_world_cup_scope(self):
        event = bot.MarketEvent("1", "FIFA World Cup final winner", "fifa-world-cup-final-winner", "world-cup", None, 10)
        with patch.object(bot, "search_events", return_value=([event], None)) as search:
            reply = bot.handle_command(
                "search",
                ["soccer", "world-cup"],
                "/search soccer world-cup",
                self.store,
                300,
                self.http,
                self.log,
            )

        search.assert_called_once()
        self.assertEqual(search.call_args.kwargs["scope"], "soccer")
        self.assertIn("World Cup", reply)


if __name__ == "__main__":
    unittest.main()
