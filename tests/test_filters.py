import unittest

import filters as flt


class FilterTests(unittest.TestCase):
    def test_world_cup_filter_matches_tag_and_keyword(self):
        by_tag = {"title": "Some market", "tags": [{"slug": "fifa-world-cup-2026"}]}
        by_title = {"title": "Will USA win the World Cup?", "tags": []}

        self.assertEqual(flt.match_event(by_tag, [flt.REGISTRY["world-cup"]]).slug, "world-cup")
        self.assertEqual(flt.match_event(by_title, [flt.REGISTRY["world-cup"]]).slug, "world-cup")

    def test_new_filters_are_registered_by_category(self):
        self.assertIn("weather", flt.CATEGORIES)
        self.assertEqual(flt.REGISTRY["fed-rates"].category, "economics")
        self.assertEqual(flt.REGISTRY["ai"].category, "technology")


if __name__ == "__main__":
    unittest.main()
