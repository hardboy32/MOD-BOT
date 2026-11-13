import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from modbot.tenant_store import EmailAlreadyExists, InvalidCredentials, TenantStore


class TenantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / "tenants.sqlite3")
        self.key = Fernet.generate_key().decode("ascii")
        self.store = TenantStore(self.db_path, self.key)

    def test_passwords_are_hashed_and_login_works(self):
        user_id = self.store.create_user("Person@example.com", "a-long-test-password")
        self.assertEqual(self.store.authenticate("person@example.com", "a-long-test-password"), user_id)
        with self.assertRaises(InvalidCredentials):
            self.store.authenticate("person@example.com", "wrong-password")

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.store.create_user("person@example.com", "a-long-test-password")
        with self.assertRaises(EmailAlreadyExists):
            self.store.create_user("PERSON@example.com", "another-long-password")

    def test_sessions_are_opaque_and_expire(self):
        user_id = self.store.create_user("person@example.com", "a-long-test-password")
        token, csrf = self.store.create_session(user_id)
        self.assertNotEqual(token, csrf)
        self.assertEqual(self.store.get_session(token)["user_id"], user_id)
        self.store.delete_session(token)
        self.assertIsNone(self.store.get_session(token))

    def test_settings_are_isolated_and_encrypted_at_rest(self):
        first = self.store.create_user("first@example.com", "a-long-test-password")
        second = self.store.create_user("second@example.com", "another-long-password")
        secret = "unique-platform-secret-value"
        self.store.save_settings(first, {"twitch": {"token": secret}})
        self.assertEqual(self.store.get_settings(first)["twitch"]["token"], secret)
        self.assertEqual(self.store.get_settings(second), {})
        with open(self.db_path, "rb") as handle:
            self.assertNotIn(secret.encode(), handle.read())


if __name__ == "__main__":
    unittest.main()
