import unittest

import app


class DuplicateSessionTests(unittest.TestCase):
    def test_duplicate_local_terminal_opens_another_local_terminal(self):
        class FakeTerm:
            connection_id=None

        win=app.Win.__new__(app.Win)
        calls=[]
        win.activeTerm=lambda: FakeTerm()
        win.openLocalTerminal=lambda: calls.append(("local",None))
        win.openConnection=lambda connection_id: calls.append(("ssh",connection_id))

        app.Win.duplicateCurrentSession(win)

        self.assertEqual(calls,[("local",None)])

    def test_duplicate_ssh_terminal_keeps_existing_behavior(self):
        class FakeTerm:
            connection_id=42

        win=app.Win.__new__(app.Win)
        calls=[]
        win.activeTerm=lambda: FakeTerm()
        win.openLocalTerminal=lambda: calls.append(("local",None))
        win.openConnection=lambda connection_id: calls.append(("ssh",connection_id))

        app.Win.duplicateCurrentSession(win)

        self.assertEqual(calls,[("ssh",42)])


if __name__=="__main__":
    unittest.main()
