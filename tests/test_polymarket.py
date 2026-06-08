import unittest
from unittest.mock import Mock, patch

import polymarket


class PolymarketSearchTests(unittest.TestCase):
    def test_event_matches_hyphenated_world_cup_query(self):
        event = {
            "title": "FIFA World Cup final winner",
            "slug": "fifa-world-cup-final-winner",
            "description": "",
            "tags": [],
        }
        self.assertTrue(polymarket.event_matches_query(event, "world-cup"))
        self.assertTrue(polymarket.event_matches_query(event, "worldcup"))

    def test_scoped_search_uses_sports_scope_but_matches_world_cup(self):
        event = {
            "id": "1",
            "title": "FIFA World Cup final winner",
            "slug": "fifa-world-cup-final-winner",
            "description": "",
            "endDate": "2026-07-19",
            "volume24hr": "1234",
            "tags": [{"slug": "fifa-world-cup-2026"}],
        }
        calls = []

        def fake_fetch(_session, params):
            calls.append(params)
            return [event]

        with patch.object(polymarket, "_fetch", fake_fetch):
            hits, err = polymarket.search_events("world-cup", scope="soccer", session=Mock())

        self.assertIsNone(err)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].filter_slug, "world-cup")
        self.assertEqual(calls[0]["tag_slug"], "sports")


if __name__ == "__main__":
    unittest.main()
