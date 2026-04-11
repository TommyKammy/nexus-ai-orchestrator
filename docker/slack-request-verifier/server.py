#!/usr/bin/env python3
import json
import hmac
import hashlib
import logging
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("slack_request_verifier")

HOST = os.getenv("SLACK_VERIFIER_HOST", "0.0.0.0")
PORT = int(os.getenv("SLACK_VERIFIER_PORT", "8089"))
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "").strip()
MAX_TIMESTAMP_SKEW_SECONDS = int(os.getenv("SLACK_MAX_TIMESTAMP_SKEW_SECONDS", "300"))
N8N_INTERNAL_BASE_URL = os.getenv("N8N_INTERNAL_BASE_URL", "http://n8n:5678").rstrip("/")


def _header_value(value):
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def _build_upstream_url(path):
    upstream_url = f"{N8N_INTERNAL_BASE_URL}{path}"
    parsed = urlsplit(upstream_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid upstream URL: {upstream_url}")
    return upstream_url


def verify_request(request, signing_secret=None, now=None):
    signing_secret = (signing_secret if signing_secret is not None else SLACK_SIGNING_SECRET).strip()
    now = int(time.time() if now is None else now)

    headers = request.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    normalized_headers = {str(key).lower(): value for key, value in headers.items()}

    slack_signature = _header_value(normalized_headers.get("x-slack-signature"))
    slack_timestamp = _header_value(normalized_headers.get("x-slack-request-timestamp"))
    raw_body = request.get("rawBody")
    if not isinstance(raw_body, str):
        raw_body = request.get("body") if isinstance(request.get("body"), str) else ""

    def fail(message):
        return 401, {
            **request,
            "status": "error",
            "message": message,
            "code": 401,
            "slack_signature": {
                "authenticated": False,
                "verification_location": "slack-request-verifier",
            },
        }

    if not signing_secret:
        return fail("Unauthorized: Slack signing secret is not configured")

    if not slack_signature or not slack_timestamp or not raw_body:
        return fail("Unauthorized: Invalid or missing Slack signature")

    try:
        timestamp = int(slack_timestamp)
    except ValueError:
        return fail("Unauthorized: Invalid or missing Slack signature")

    if abs(now - timestamp) > MAX_TIMESTAMP_SKEW_SECONDS:
        return fail("Unauthorized: Invalid or expired Slack signature")

    signature_base_string = f"v0:{slack_timestamp}:{raw_body}"
    expected_signature = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        signature_base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signatures_match = hmac.compare_digest(expected_signature, slack_signature)
    if not signatures_match:
        return fail("Unauthorized: Invalid or missing Slack signature")

    return 200, {
        **request,
        "slack_signature": {
            "authenticated": True,
            "verification_location": "slack-request-verifier",
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SlackRequestVerifier/1.0"

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "error": "Not Found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""

        if self.path == "/verify":
            self._handle_verify_request(body)
            return

        request_payload = {
            "headers": dict(self.headers.items()),
            "rawBody": body.decode("utf-8"),
            "body": body.decode("utf-8"),
        }
        status, response = verify_request(request_payload)
        LOGGER.info("verified status=%s authenticated=%s", status, response.get("slack_signature", {}).get("authenticated"))
        if status != 200:
            self._send_json(status, response)
            return

        self._proxy_to_n8n(body)

    def log_message(self, format, *args):
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_verify_request(self, body):
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid JSON"})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "Request payload must be an object"})
            return

        status, response = verify_request(payload)
        LOGGER.info("verified status=%s authenticated=%s", status, response.get("slack_signature", {}).get("authenticated"))
        self._send_json(200, response)

    def _proxy_to_n8n(self, body):
        try:
            upstream_url = _build_upstream_url(self.path)
        except ValueError as error:
            LOGGER.error(
                "Invalid upstream target base=%s path=%s error=%s",
                N8N_INTERNAL_BASE_URL,
                self.path,
                error,
            )
            self._send_json(502, {"ok": False, "error": "Upstream unavailable"})
            return

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        try:
            request = urllib.request.Request(
                upstream_url,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read()
                self.send_response(response.getcode())
                for key, value in response.getheaders():
                    if key.lower() in {"transfer-encoding", "connection"}:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as error:
            response_body = error.read()
            self.send_response(error.code)
            for key, value in error.headers.items():
                if key.lower() in {"transfer-encoding", "connection"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)
        except urllib.error.URLError as error:
            LOGGER.error(
                "Upstream request failed base=%s path=%s error=%s",
                N8N_INTERNAL_BASE_URL,
                self.path,
                error,
            )
            self._send_json(502, {"ok": False, "error": "Upstream unavailable"})


def main():
    server = HTTPServer((HOST, PORT), Handler)
    LOGGER.info("Starting Slack request verifier on %s:%s", HOST, PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
