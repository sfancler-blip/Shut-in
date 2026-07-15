import json

from shutin import alerts

THEATER = {"id": "hollywood-theatre", "name": "Hollywood Theatre"}
RUN = {"id": 7, "outcome": "error", "error_detail": "HTTP 500", "screenings_found": 0,
       "screenings_new": 0, "screenings_updated": 0, "screenings_cancelled": 0}
CFG = {"github_token": "t", "github_repo": "user/shut-in", "smtp": None, "alert_email": None}


def test_failure_creates_issue_when_none_open(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return []  # no open issue
        return {"number": 12}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_failure(THEATER, RUN, CFG)
    methods = [c[0] for c in calls]
    assert methods == ["GET", "POST"]
    assert "[scraper-broken] hollywood-theatre" in json.dumps(calls[1][2])


def test_repeat_failure_comments_on_existing_issue(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return [{"number": 12, "title": "[scraper-broken] hollywood-theatre"}]
        return {}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_failure(THEATER, RUN, CFG)
    assert any("/issues/12/comments" in c[1] for c in calls if c[0] == "POST")


def test_recovery_closes_issue(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return [{"number": 12, "title": "[scraper-broken] hollywood-theatre"}]
        return {}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_recovery(THEATER, CFG)
    assert any(c[0] == "PATCH" and c[2] == {"state": "closed"} for c in calls)


def test_missing_channel_config_is_nonfatal(monkeypatch, capsys):
    alerts.notify_failure(THEATER, RUN, {"github_token": None, "github_repo": None,
                                         "smtp": None, "alert_email": None})
    # nothing raised; warning printed
    assert "disabled" in capsys.readouterr().out.lower()
