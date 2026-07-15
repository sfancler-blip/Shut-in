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


class _FakeSMTP:
    """Records calls; monkeypatched in place of smtplib.SMTP."""
    sent = {}

    def __init__(self, host, port):
        _FakeSMTP.sent["host"] = host
        _FakeSMTP.sent["port"] = port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        _FakeSMTP.sent["starttls"] = True

    def login(self, user, password):
        _FakeSMTP.sent["login"] = (user, password)

    def send_message(self, msg):
        _FakeSMTP.sent["msg"] = msg


class _RaisingSMTP:
    def __init__(self, host, port):
        raise OSError("connection refused")


SMTP_CFG = {"github_token": "t", "github_repo": "user/shut-in",
            "smtp": {"host": "smtp.example.com", "port": 587,
                     "user": "u@example.com", "password": "p"},
            "alert_email": "ops@example.com"}


def test_smtp_happy_path_sends_email(monkeypatch):
    _FakeSMTP.sent = {}
    monkeypatch.setattr(alerts, "_github_api",
                        lambda method, url, cfg, body=None: [] if method == "GET" else {"number": 1})
    monkeypatch.setattr(alerts.smtplib, "SMTP", _FakeSMTP)
    alerts.notify_failure(THEATER, RUN, SMTP_CFG)
    assert _FakeSMTP.sent["msg"]["To"] == "ops@example.com"
    assert "hollywood-theatre" in _FakeSMTP.sent["msg"]["Subject"]
    assert _FakeSMTP.sent["login"] == ("u@example.com", "p")


def test_github_failure_is_nonfatal_and_email_still_attempted(monkeypatch, capsys):
    _FakeSMTP.sent = {}

    def raising_api(*a, **k):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(alerts, "_github_api", raising_api)
    monkeypatch.setattr(alerts.smtplib, "SMTP", _FakeSMTP)
    alerts.notify_failure(THEATER, RUN, SMTP_CFG)  # must not raise
    assert "msg" in _FakeSMTP.sent  # email channel still attempted
    assert "failed" in capsys.readouterr().out.lower()


def test_smtp_failure_is_nonfatal(monkeypatch, capsys):
    monkeypatch.setattr(alerts, "_github_api",
                        lambda method, url, cfg, body=None: [] if method == "GET" else {"number": 1})
    monkeypatch.setattr(alerts.smtplib, "SMTP", _RaisingSMTP)
    alerts.notify_failure(THEATER, RUN, SMTP_CFG)  # must not raise
    assert "failed" in capsys.readouterr().out.lower()


def test_recovery_github_failure_is_nonfatal(monkeypatch, capsys):
    def raising_api(*a, **k):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(alerts, "_github_api", raising_api)
    alerts.notify_recovery(THEATER, CFG)  # must not raise
    assert "failed" in capsys.readouterr().out.lower()
