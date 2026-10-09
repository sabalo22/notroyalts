import unittest

import app
import pyte


class ScrollbackSnapshotTests(unittest.TestCase):
    def test_row_plain_text_trims_terminal_padding(self):
        screen=app.CompatibleScreen(10,2)
        stream=pyte.Stream(screen)
        stream.feed("abc")

        self.assertEqual(app.terminal_row_plain_text(screen.buffer[0],10),"abc")

    def test_snapshot_contains_history_and_current_screen(self):
        screen=app.CompatibleHistoryScreen(20,3,history=100,ratio=0.5)
        stream=pyte.Stream(screen)

        for n in range(8):
            stream.feed(f"line{n}\r\n")

        text,current_start=app.terminal_scrollback_snapshot(screen)

        self.assertIn("line0",text)
        self.assertIn("line7",text)
        self.assertGreater(current_start,0)

    def test_snapshot_does_not_change_history_position(self):
        screen=app.CompatibleHistoryScreen(20,3,history=100,ratio=0.5)
        stream=pyte.Stream(screen)

        for n in range(8):
            stream.feed(f"line{n}\r\n")

        screen.prev_page()
        before=screen.history.position

        app.terminal_scrollback_snapshot(screen)

        self.assertEqual(screen.history.position,before)


class CopyModeBehaviorTests(unittest.TestCase):
    def test_copy_does_not_exit_copy_mode(self):
        class FakeCursor:
            def hasSelection(self):
                return True
            def selectedText(self):
                return "one\u2029two"
            def selectionStart(self):
                return 0

        class FakeBlock:
            def blockNumber(self):
                return 0

        class FakeDocument:
            def findBlock(self,pos):
                return FakeBlock()

        class FakeRow:
            notroyalts_soft_wrapped=False

        class FakeClipboard:
            def __init__(self):
                self.value=None
            def setText(self,value):
                self.value=value

        term=app.Term.__new__(app.Term)
        term.copy_mode=True
        term.copy_snapshot_rows=[FakeRow(),FakeRow()]
        term.textCursor=lambda: FakeCursor()
        term.document=lambda: FakeDocument()
        clipboard=FakeClipboard()

        original=app.QApplication.clipboard
        app.QApplication.clipboard=staticmethod(lambda: clipboard)
        try:
            app.Term.copy_selection(term)
        finally:
            app.QApplication.clipboard=original

        self.assertTrue(term.copy_mode)
        self.assertEqual(clipboard.value,"one\ntwo")


if __name__=="__main__":
    unittest.main()
