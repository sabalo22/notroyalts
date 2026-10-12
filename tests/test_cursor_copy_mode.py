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
    def test_copy_mode_can_use_remembered_live_cursor_after_history_hides_pyte_cursor(self):
        term=app.Term.__new__(app.Term)
        term.copy_mode=True
        term.history_view=True
        term.copy_snapshot_live_start=100
        term.live_cursor_y=5
        term.live_cursor_x=3
        term.live_cursor_hidden=False

        class HiddenCursor:
            hidden=True
            y=0
            x=0

        class FakeScreen:
            cursor=HiddenCursor()

        class FakeBlock:
            def isValid(self):
                return True
            def position(self):
                return 200
            def length(self):
                return 20

        class FakeDocument:
            def blockCount(self):
                return 200
            def findBlockByNumber(self,row):
                self.row=row
                return FakeBlock()

        doc=FakeDocument()
        term.scr=FakeScreen()
        term.document=lambda: doc

        cursor=app.Term.cursor_document_position(term)

        self.assertIsNotNone(cursor)
        self.assertEqual(doc.row,105)


