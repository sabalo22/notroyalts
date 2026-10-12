import unittest

import app


class CursorDocumentRowTests(unittest.TestCase):
    def test_live_cursor_uses_visible_screen_row(self):
        self.assertEqual(
            app.terminal_cursor_document_row(False,False,0,7),
            7,
        )

    def test_history_view_hides_live_cursor(self):
        self.assertIsNone(
            app.terminal_cursor_document_row(False,True,0,7)
        )

    def test_copy_mode_maps_cursor_into_scrollback_snapshot(self):
        self.assertEqual(
            app.terminal_cursor_document_row(True,True,120,7),
            127,
        )


if __name__=="__main__":
    unittest.main()
