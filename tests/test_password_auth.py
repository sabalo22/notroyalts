import unittest

import app


class SSHAuthenticationArgsTests(unittest.TestCase):
    def base_connection(self,**overrides):
        data={
            "host":"example.com",
            "port":22,
            "username":"admin",
            "auth_method":"key",
            "identity_file":"~/.ssh/id_ed25519",
            "proxy_jump":"",
            "extra_args":"",
        }
        data.update(overrides)
        return data

    def test_key_auth_keeps_identity_file_behavior(self):
        args=app.sshargs(self.base_connection())

        self.assertIn("-i",args)
        self.assertIn(
            app.os.path.expanduser("~/.ssh/id_ed25519"),
            args,
        )
        self.assertNotIn("PubkeyAuthentication=no",args)

    def test_password_auth_disables_public_key_attempts(self):
        args=app.sshargs(
            self.base_connection(
                auth_method="password",
                identity_file="~/.ssh/id_ed25519",
            )
        )

        self.assertNotIn("-i",args)
        self.assertIn("PubkeyAuthentication=no",args)
        self.assertIn(
            "PreferredAuthentications=keyboard-interactive,password",
            args,
        )
        self.assertEqual(args[-1],"admin@example.com")

    def test_password_mode_does_not_put_password_in_ssh_args(self):
        connection=self.base_connection(auth_method="password")
        connection["password"]="super-secret"

        args=app.sshargs(connection)

        self.assertNotIn("super-secret",args)


if __name__=="__main__":
    unittest.main()
