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


class RememberedLiveCursorTests(unittest.TestCase):
    def test_copy_mode_uses_remembered_live_cursor_even_if_pyte_cursor_is_hidden(self):
        class HiddenCursor:
            hidden=True
            y=0
            x=0

        y,x,hidden=app.terminal_cursor_state(
            True,
            5,
            3,
            False,
            HiddenCursor(),
        )

        self.assertEqual((y,x,hidden),(5,3,False))

    def test_live_mode_uses_current_pyte_cursor(self):
        class LiveCursor:
            hidden=False
            y=9
            x=4

        y,x,hidden=app.terminal_cursor_state(
            False,
            5,
            3,
            False,
            LiveCursor(),
        )

        self.assertEqual((y,x,hidden),(9,4,False))


if __name__=="__main__":
    unittest.main()
