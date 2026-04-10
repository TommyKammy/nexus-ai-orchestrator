import importlib.util
import hmac
import hashlib
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "docker" / "slack-request-verifier" / "server.py"
)
SPEC = importlib.util.spec_from_file_location("slack_request_verifier", MODULE_PATH)
slack_request_verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(slack_request_verifier)


class SlackRequestVerifierTests(unittest.TestCase):
    def _signed_request(self, secret="signing-secret", timestamp=1_710_000_000):
        raw_body = "team_id=T123&channel_id=C123&user_id=U123&command=%2Fai&text=hello"
        signature_base_string = f"v0:{timestamp}:{raw_body}"
        signature = "v0=" + hmac.new(
            secret.encode("utf-8"),
            signature_base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "headers": {
                "X-Slack-Request-Timestamp": str(timestamp),
                "X-Slack-Signature": signature,
            },
            "rawBody": raw_body,
            "body": raw_body,
        }

    def test_accepts_valid_signature(self):
        request = self._signed_request()
        status, payload = slack_request_verifier.verify_request(
            request, signing_secret="signing-secret", now=1_710_000_000
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["slack_signature"]["authenticated"])
        self.assertEqual(
            payload["slack_signature"]["verification_location"],
            "slack-request-verifier",
        )

    def test_rejects_invalid_signature(self):
        request = self._signed_request()
        request["headers"]["X-Slack-Signature"] = "v0=bogus"
        status, payload = slack_request_verifier.verify_request(
            request, signing_secret="signing-secret", now=1_710_000_000
        )

        self.assertEqual(status, 401)
        self.assertFalse(payload["slack_signature"]["authenticated"])
        self.assertIn("Invalid or missing Slack signature", payload["message"])

    def test_rejects_replayed_request(self):
        request = self._signed_request(timestamp=1_710_000_000)
        status, payload = slack_request_verifier.verify_request(
            request, signing_secret="signing-secret", now=1_710_000_301
        )

        self.assertEqual(status, 401)
        self.assertFalse(payload["slack_signature"]["authenticated"])
        self.assertIn("expired Slack signature", payload["message"])


if __name__ == "__main__":
    unittest.main()
