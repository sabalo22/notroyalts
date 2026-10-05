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


if __name__=="__main__":
    unittest.main()
