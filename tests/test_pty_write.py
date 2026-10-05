import unittest
from unittest.mock import patch

import app


class PtyTransmitBufferTests(unittest.TestCase):
    def make_term(self):
        term=app.Term.__new__(app.Term)
        term.fd=42
        term.tx_buffer=bytearray()
        return term

    def test_partial_write_queues_remainder(self):
        term=self.make_term()

        with patch.object(app.os,"write",return_value=2) as write:
            term.send(b"abcdef")

        write.assert_called_once_with(42,b"abcdef")
        self.assertEqual(term.tx_buffer,b"cdef")

    def test_new_input_does_not_overtake_queued_bytes(self):
        term=self.make_term()
        term.tx_buffer.extend(b"older")

        with patch.object(app.os,"write") as write:
            term.send(b"new")

        write.assert_not_called()
        self.assertEqual(term.tx_buffer,b"oldernew")

    def test_pump_removes_only_bytes_actually_written(self):
        term=self.make_term()
        term.tx_buffer.extend(b"abcdef")

        with patch.object(app.os,"write",return_value=3):
            term.pump_input()

        self.assertEqual(term.tx_buffer,b"def")

    def test_blocking_write_keeps_entire_payload_queued(self):
        term=self.make_term()

        with patch.object(app.os,"write",side_effect=BlockingIOError):
            term.send(b"clipboard")

        self.assertEqual(term.tx_buffer,b"clipboard")


if __name__=="__main__":
    unittest.main()
