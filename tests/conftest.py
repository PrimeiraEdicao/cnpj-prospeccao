import pytest


@pytest.fixture(autouse=True)
def explicit_development_mode(monkeypatch):
    # Existing prototype regressions opt in explicitly; production defaults remain closed.
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
