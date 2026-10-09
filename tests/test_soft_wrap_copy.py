import unittest

import app
import pyte


class SoftWrapTrackingTests(unittest.TestCase):
    def test_auto_wrap_is_marked_soft(self):
        screen=app.CompatibleHistoryScreen(10,3,history=20,ratio=0.5)
        stream=pyte.Stream(screen)

        stream.feed("abcdefghijk")

        self.assertTrue(app.terminal_row_soft_wrapped(screen.buffer[0]))
        self.assertEqual(app.terminal_row_plain_text(screen.buffer[0],10),"abcdefghij")
        self.assertEqual(app.terminal_row_plain_text(screen.buffer[1],10),"k")

    def test_real_linefeed_is_not_soft_wrap(self):
        screen=app.CompatibleHistoryScreen(10,3,history=20,ratio=0.5)
        stream=pyte.Stream(screen)

        stream.feed("abcdefghij\r\nnext")

        self.assertFalse(app.terminal_row_soft_wrapped(screen.buffer[0]))
        self.assertEqual(app.terminal_row_plain_text(screen.buffer[1],10),"next")

    def test_soft_wrap_metadata_follows_row_into_history(self):
        screen=app.CompatibleHistoryScreen(5,2,history=20,ratio=0.5)
        stream=pyte.Stream(screen)

        stream.feed("abcdef")
        stream.feed("\r\nline2\r\nline3")

        rows,_=app.terminal_scrollback_rows(screen)
        wrapped=[r for r in rows if app.terminal_row_plain_text(r,5)=="abcde"]

        self.assertEqual(len(wrapped),1)
        self.assertTrue(app.terminal_row_soft_wrapped(wrapped[0]))


class ClipboardReconstructionTests(unittest.TestCase):
    def test_soft_wrapped_rows_are_rejoined(self):
        screen=app.CompatibleHistoryScreen(10,3,history=20,ratio=0.5)
        stream=pyte.Stream(screen)
        stream.feed("abcdefghijk")

        rows=[screen.buffer[y] for y in range(screen.lines)]
        selected="abcdefghij\u2029k"

        self.assertEqual(
            app.terminal_selection_plain_text(selected,rows,0),
            "abcdefghijk",
        )

    def test_real_line_endings_are_preserved(self):
        screen=app.CompatibleHistoryScreen(10,3,history=20,ratio=0.5)
        stream=pyte.Stream(screen)
        stream.feed("abc\r\ndef")

        rows=[screen.buffer[y] for y in range(screen.lines)]
        selected="abc\u2029def"

        self.assertEqual(
            app.terminal_selection_plain_text(selected,rows,0),
            "abc\ndef",
        )

    def test_pem_style_hard_lines_survive_terminal_soft_wrap(self):
        screen=app.CompatibleHistoryScreen(8,6,history=50,ratio=0.5)
        stream=pyte.Stream(screen)
        stream.feed("ABCDEFGHIJKLMNOP\r\nQRSTUVWX")

        rows=[screen.buffer[y] for y in range(screen.lines)]
        # Qt represents paragraph boundaries in selectedText() as U+2029.
        selected="ABCDEFGH\u2029IJKLMNOP\u2029QRSTUVWX"

        self.assertEqual(
            app.terminal_selection_plain_text(selected,rows,0),
            "ABCDEFGHIJKLMNOP\nQRSTUVWX",
        )


if __name__=="__main__":
    unittest.main()
