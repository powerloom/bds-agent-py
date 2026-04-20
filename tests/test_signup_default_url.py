from bds_agent.signup_api import DEFAULT_SIGNUP_BASE_URL, default_signup_base_url


def test_default_signup_base_url_uses_powerloom_io(monkeypatch) -> None:
    monkeypatch.delenv("BDS_AGENT_SIGNUP_URL", raising=False)
    assert default_signup_base_url() == DEFAULT_SIGNUP_BASE_URL


def test_default_signup_base_url_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BDS_AGENT_SIGNUP_URL", "http://127.0.0.1:9999")
    assert default_signup_base_url() == "http://127.0.0.1:9999"
