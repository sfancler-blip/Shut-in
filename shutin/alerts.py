"""Dual-channel alerting (F7): operator email + one GitHub issue per broken theater."""
import os
import smtplib
from email.message import EmailMessage

from curl_cffi import requests

LABEL = "scraper-broken"


def config_from_env() -> dict:
    smtp = None
    if os.environ.get("SMTP_HOST"):
        smtp = {
            "host": os.environ["SMTP_HOST"],
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": os.environ.get("SMTP_USER"),
            "password": os.environ.get("SMTP_PASS"),
        }
    return {
        "github_token": os.environ.get("GITHUB_TOKEN"),
        "github_repo": os.environ.get("GITHUB_REPO"),
        "smtp": smtp,
        "alert_email": os.environ.get("ALERT_EMAIL"),
    }


def _issue_title(theater_id: str) -> str:
    return f"[scraper-broken] {theater_id}"


def _github_api(method: str, url: str, cfg: dict, body: dict | None = None):
    r = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {cfg['github_token']}",
            "Accept": "application/vnd.github+json",
        },
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def _find_open_issue(theater: dict, cfg: dict):
    issues = _github_api(
        "GET",
        f"https://api.github.com/repos/{cfg['github_repo']}/issues?labels={LABEL}&state=open",
        cfg,
    )
    want = _issue_title(theater["id"])
    return next((i for i in issues if i["title"] == want), None)


def _failure_body(theater: dict, run: dict) -> str:
    return (
        f"Run {run['id']} for **{theater['name']}** failed: `{run['outcome']}`\n\n"
        f"```\n{run.get('error_detail') or 'zero screenings from a previously healthy theater'}\n```\n\n"
        f"Repair loop:\n"
        f"1. `shutin record-fixtures --theater {theater['id']}`\n"
        f"2. Follow `.claude/skills/debug-theater-scraper`\n"
    )


def notify_failure(theater: dict, run: dict, cfg: dict) -> None:
    if cfg.get("github_token") and cfg.get("github_repo"):
        try:
            base = f"https://api.github.com/repos/{cfg['github_repo']}/issues"
            existing = _find_open_issue(theater, cfg)
            if existing:
                _github_api("POST", f"{base}/{existing['number']}/comments", cfg,
                            {"body": _failure_body(theater, run)})
            else:
                _github_api("POST", base, cfg, {
                    "title": _issue_title(theater["id"]),
                    "labels": [LABEL],
                    "body": _failure_body(theater, run),
                })
        except Exception as e:
            print(f"alerts: github channel failed: {e}")
    else:
        print("alerts: github channel disabled (GITHUB_TOKEN/GITHUB_REPO unset)")

    if cfg.get("smtp") and cfg.get("alert_email"):
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[shut-in] {theater['id']} scrape {run['outcome']}"
            msg["From"] = cfg["smtp"]["user"] or "shutin@localhost"
            msg["To"] = cfg["alert_email"]
            msg.set_content(_failure_body(theater, run))
            with smtplib.SMTP(cfg["smtp"]["host"], cfg["smtp"]["port"]) as s:
                s.starttls()
                if cfg["smtp"]["user"]:
                    s.login(cfg["smtp"]["user"], cfg["smtp"]["password"])
                s.send_message(msg)
        except Exception as e:
            print(f"alerts: email channel failed: {e}")
    else:
        print("alerts: email channel disabled (SMTP_*/ALERT_EMAIL unset)")


def notify_recovery(theater: dict, cfg: dict) -> None:
    if not (cfg.get("github_token") and cfg.get("github_repo")):
        print("alerts: github channel disabled (GITHUB_TOKEN/GITHUB_REPO unset)")
        return
    try:
        existing = _find_open_issue(theater, cfg)
        if existing:
            base = f"https://api.github.com/repos/{cfg['github_repo']}/issues/{existing['number']}"
            _github_api("POST", f"{base}/comments", cfg,
                        {"body": f"{theater['name']} recovered — latest run green. Auto-closing."})
            _github_api("PATCH", base, cfg, {"state": "closed"})
    except Exception as e:
        print(f"alerts: github channel failed: {e}")
