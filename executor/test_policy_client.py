import pytest

from executor.policy_client import PolicyClient


def test_policy_client_defaults_to_enforce_and_fail_closed(monkeypatch):
    monkeypatch.delenv("POLICY_MODE", raising=False)
    monkeypatch.delenv("POLICY_FAIL_MODE", raising=False)

    client = PolicyClient()

    assert client.mode == "enforce"
    assert client.fail_mode == "closed"


def test_policy_client_fallback_denies_when_opa_unavailable(monkeypatch):
    monkeypatch.delenv("POLICY_FAIL_MODE", raising=False)

    client = PolicyClient()
    result = client._fallback_result("opa unavailable")

    assert result["decision"] == "deny"
    assert result["allow"] is False
    assert result["requires_approval"] is True
    assert result["reasons"] == ["policy_unavailable"]
    assert result["error"] == "opa unavailable"


def test_policy_client_rejects_unsafe_configuration_without_override(monkeypatch):
    monkeypatch.setenv("POLICY_MODE", "shadow")
    monkeypatch.setenv("POLICY_FAIL_MODE", "open")
    monkeypatch.delenv("POLICY_ALLOW_UNSAFE", raising=False)

    with pytest.raises(ValueError, match="Unsafe policy configuration requires explicit operator intent"):
        PolicyClient()


def test_policy_client_allows_unsafe_configuration_with_explicit_override(monkeypatch, caplog):
    monkeypatch.setenv("POLICY_MODE", "shadow")
    monkeypatch.setenv("POLICY_FAIL_MODE", "open")
    monkeypatch.setenv("POLICY_ALLOW_UNSAFE", "true")

    with caplog.at_level("WARNING"):
        client = PolicyClient()

    assert client.mode == "shadow"
    assert client.fail_mode == "open"
    assert "Unsafe policy override enabled" in caplog.text
