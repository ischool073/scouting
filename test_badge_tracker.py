import unittest

from badge_tracker import percent_complete, is_earned


class TestPercentComplete(unittest.TestCase):
    def test_partial_progress(self):
        self.assertEqual(percent_complete(3, 5), 60.0)

    def test_no_progress(self):
        self.assertEqual(percent_complete(0, 5), 0.0)

    def test_full_progress(self):
        self.assertEqual(percent_complete(5, 5), 100.0)

    def test_invalid_total_raises(self):
        with self.assertRaises(ValueError):
            percent_complete(1, 0)

    def test_completed_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            percent_complete(6, 5)

    def test_negative_completed_raises(self):
        with self.assertRaises(ValueError):
            percent_complete(-1, 5)


class TestIsEarned(unittest.TestCase):
    def test_not_earned(self):
        self.assertFalse(is_earned(4, 5))

    def test_earned(self):
        self.assertTrue(is_earned(5, 5))


if __name__ == "__main__":
    unittest.main()
