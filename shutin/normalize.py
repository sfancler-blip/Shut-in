import re
from datetime import datetime
from zoneinfo import ZoneInfo

_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_NOISE = re.compile(
    r"\s*(\((?:19|20)\d{2}\)|\(\d+mm\)|in \d+mm|\(3-?d\)|3-?d)\s*$", re.IGNORECASE
)


def normalize_title(title: str) -> str:
    t = title.strip()
    while True:
        t2 = _NOISE.sub("", t)
        if t2 == t:
            break
        t = t2
    t = _ARTICLES.sub("", t)
    return re.sub(r"\s+", " ", t).lower().strip()


def to_utc(local: datetime, tz: str) -> tuple[str, str]:
    aware = local.replace(tzinfo=ZoneInfo(tz))
    utc = aware.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ"), local.strftime("%Y-%m-%d %H:%M")
