import time

import pytest

from shutin import fetch


class FakeResp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_retries_on_5xx_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp(500 if len(calls) < 3 else 200)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    r = fetch.get("https://example.com/a")
    assert r.status_code == 200
    assert len(calls) == 3


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: FakeResp(500))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        fetch.get("https://example.com/a", attempts=3)


def test_4xx_raises_immediately(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp(403)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    with pytest.raises(RuntimeError):
        fetch.get("https://example.com/a")
    assert len(calls) == 1


def test_same_host_spacing(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: FakeResp(200))
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    fetch._last_hit.clear()
    fetch.get("https://example.com/a")
    fetch.get("https://example.com/b")
    assert sum(sleeps) >= 0.5  # second same-host call waited
