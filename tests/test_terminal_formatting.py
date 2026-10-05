import unittest
from types import SimpleNamespace

import app


class TerminalCellFormattingTests(unittest.TestCase):
    def make_cell(self,data,underscore=False,strikethrough=False):
        return SimpleNamespace(
            data=data,
            fg="default",
            bg="default",
            bold=False,
            italics=False,
            underscore=underscore,
            strikethrough=strikethrough,
            reverse=False,
        )

    def test_visible_character_keeps_underline(self):
        key=app.terminal_cell_format_key(self.make_cell("x",underscore=True))
        self.assertTrue(key[4])

    def test_blank_space_drops_underline(self):
        key=app.terminal_cell_format_key(self.make_cell(" ",underscore=True))
        self.assertFalse(key[4])

    def test_blank_space_drops_strikethrough(self):
        key=app.terminal_cell_format_key(self.make_cell(" ",strikethrough=True))
        self.assertFalse(key[5])

    def test_blank_space_preserves_background_and_reverse(self):
        cell=self.make_cell(" ")
        cell.bg="blue"
        cell.reverse=True
        key=app.terminal_cell_format_key(cell)
        self.assertEqual(key[1],"blue")
        self.assertTrue(key[6])


if __name__=="__main__":
    unittest.main()
