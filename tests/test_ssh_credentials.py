import unittest
from unittest.mock import patch

import ssh_credentials


class Result:
    def __init__(self,returncode=0,stdout="",stderr=""):
        self.returncode=returncode
        self.stdout=stdout
        self.stderr=stderr


class SSHCredentialKeychainTests(unittest.TestCase):
    def test_account_is_scoped_to_connection_id(self):
        self.assertEqual(
            ssh_credentials._account(42),
            "connection-42",
        )

    @patch("ssh_credentials._security")
    def test_get_password_reads_keychain_secret(self,security):
        security.return_value=Result(stdout="secret\n")

        self.assertEqual(ssh_credentials.get_password(7),"secret")
        self.assertIn("-w",security.call_args.args[0])

    @patch("ssh_credentials._security")
    def test_has_password_checks_metadata_without_reading_secret(self,security):
        security.return_value=Result(returncode=0)

        self.assertTrue(ssh_credentials.has_password(7))
        self.assertNotIn("-w",security.call_args.args[0])

    @patch("ssh_credentials._security")
    def test_set_password_uses_keychain_service(self,security):
        security.return_value=Result(returncode=0)

        ssh_credentials.set_password(7,"secret","Example")

        args=security.call_args.args[0]
        self.assertIn("add-generic-password",args)
        self.assertIn(ssh_credentials.KEYCHAIN_SERVICE,args)
        self.assertIn("connection-7",args)
        self.assertIn("secret",args)


if __name__=="__main__":
    unittest.main()
