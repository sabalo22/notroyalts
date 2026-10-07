import unittest

import app


class NaturalSortTests(unittest.TestCase):
    def test_numeric_suffixes_sort_naturally(self):
        names=["stor10","stor11","stor6","stor7","stor8","stor9","stor1","stor2"]
        self.assertEqual(
            sorted(names,key=app.natural_sort_key),
            ["stor1","stor2","stor6","stor7","stor8","stor9","stor10","stor11"],
        )

    def test_sort_is_case_insensitive(self):
        names=["Store10","store2","STORE1"]
        self.assertEqual(
            sorted(names,key=app.natural_sort_key),
            ["STORE1","store2","Store10"],
        )

    def test_numbers_inside_names_are_numeric(self):
        names=["node2-prod","node10-prod","node1-prod"]
        self.assertEqual(
            sorted(names,key=app.natural_sort_key),
            ["node1-prod","node2-prod","node10-prod"],
        )


if __name__=="__main__":
    unittest.main()
