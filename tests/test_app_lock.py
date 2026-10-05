import unittest

import app_lock


class AppLockRecordTests(unittest.TestCase):
    def test_password_round_trip(self):
        record = app_lock._make_record(
            "correct horse battery staple",
            salt=b"0123456789abcdef",
            iterations=1000,
        )
        self.assertTrue(
            app_lock._verify_record("correct horse battery staple", record)
        )
        self.assertFalse(app_lock._verify_record("wrong password", record))

    def test_empty_password_is_rejected(self):
        with self.assertRaises(ValueError):
            app_lock._make_record("")

    def test_malformed_record_fails_closed(self):
        self.assertFalse(app_lock._verify_record("anything", "not-a-valid-record"))

    def test_unknown_record_version_fails_closed(self):
        record = app_lock._make_record(
            "password",
            salt=b"0123456789abcdef",
            iterations=1000,
        )
        record = record.replace("v1$", "v2$", 1)
        self.assertFalse(app_lock._verify_record("password", record))


if __name__ == "__main__":
    unittest.main()
