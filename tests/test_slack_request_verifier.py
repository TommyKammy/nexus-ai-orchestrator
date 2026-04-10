import importlib.util
import hmac
import hashlib
import unittest
from pathlib import Path
from unittest import mock
import urllib.error


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

    def _handler(self, path="/webhook/slack-command"):
        handler = object.__new__(slack_request_verifier.Handler)
        handler.path = path
        handler.headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "example.com",
            "Content-Length": "4",
            "Connection": "keep-alive",
        }
        handler._send_json = mock.Mock()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.wfile = mock.Mock()
        return handler

    def test_proxy_rejects_invalid_upstream_scheme(self):
        handler = self._handler()

        with mock.patch.object(
            slack_request_verifier, "N8N_INTERNAL_BASE_URL", "file:///tmp/n8n"
        ):
            handler._proxy_to_n8n(b"body")

        handler._send_json.assert_called_once_with(
            502, {"ok": False, "error": "Upstream unavailable"}
        )

    def test_proxy_returns_bad_gateway_on_url_error(self):
        handler = self._handler()

        with mock.patch.object(
            slack_request_verifier, "N8N_INTERNAL_BASE_URL", "http://n8n:5678"
        ), mock.patch.object(
            slack_request_verifier.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            handler._proxy_to_n8n(b"body")

        handler._send_json.assert_called_once_with(
            502, {"ok": False, "error": "Upstream unavailable"}
        )


if __name__ == "__main__":
    unittest.main()
