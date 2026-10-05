import unittest

import app
import pyte


class PrivateSgrCompatibilityTests(unittest.TestCase):
    def test_private_sgr_does_not_crash_history_screen(self):
        screen=app.CompatibleHistoryScreen(80,24,history=100)
        stream=pyte.Stream(screen)

        stream.feed("\x1b[?4mhello")

        self.assertIn("hello", screen.display[0])
        self.assertFalse(screen.buffer[0][0].underscore)

    def test_private_sgr_does_not_crash_alt_screen(self):
        screen=app.CompatibleScreen(80,24)
        stream=pyte.Stream(screen)

        stream.feed("\x1b[?4;0mhello")

        self.assertIn("hello", screen.display[0])


if __name__=="__main__":
    unittest.main()
