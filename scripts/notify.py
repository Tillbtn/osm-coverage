#!/usr/bin/env python3
"""Push notifications via an ntfy server.

Alerts are raised on state changes, never per log line: track_failure() counts
consecutive failures of one operation across cron runs and only notifies once
the count reaches its threshold (then at most one reminder per day), and
track_success() resets the count and sends a short recovery note if an alert
went out. The counters live in data/.notify_state.json; edit_state() gives
read-modify-write access to that file.

Configuration via environment (docker compose passes it from deployment/.env):

    NTFY_URL            server base URL. Unset = print only.
    NTFY_TOKEN          access token of a publish-only ntfy user
    NTFY_TOPIC_ALERTS   topic for failures (default: osm-alerts)
    NTFY_TOPIC_ALKIS    topic for new ALKIS data (default: osm-alkis)
    NOTIFY_STATE_FILE   default: data/.notify_state.json

CLI:
    python scripts/notify.py test alerts
    python scripts/notify.py send alerts "Title" "Message" [--priority high]
    python scripts/notify.py fail wfs:aachen "HTTP 502" --threshold 2 [--title ...]
    python scripts/notify.py ok wfs:aachen
    python scripts/notify.py status
"""

import argparse
import contextlib
import datetime
import json
import os
import sys

import requests

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STATE_FILE = os.path.join(_REPO_ROOT, "data", ".notify_state.json")
DEFAULT_TOPICS = {"alerts": "osm-alerts", "alkis": "osm-alkis"}
PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}
TIMEOUT = 10
MAX_MESSAGE_BYTES = 4000  # ntfy turns longer messages into attachments
DEFAULT_REMIND_EVERY = datetime.timedelta(hours=24)


def _now():
    return datetime.datetime.now().replace(microsecond=0)


def _topic(channel):
    if channel not in DEFAULT_TOPICS:
        raise ValueError(f"unknown channel '{channel}' (known: {', '.join(DEFAULT_TOPICS)})")
    return os.environ.get(f"NTFY_TOPIC_{channel.upper()}") or DEFAULT_TOPICS[channel]


def _truncate(text, limit=MAX_MESSAGE_BYTES):
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit - 3].decode("utf-8", errors="ignore") + "..."


def send(channel, title, message, priority="default", tags=(), click=None):
    """Publish one notification. Returns True if the server accepted it.

    Uses ntfy's JSON API: header-based publishing would garble umlauts in the
    title, since HTTP headers are latin-1.
    """
    url = os.environ.get("NTFY_URL")
    if not url:
        print(f"[notify] not configured, would send ({channel}): {title} - {message}")
        return False

    payload = {
        "topic": _topic(channel),
        "title": title,
        "message": _truncate(message),
        "priority": PRIORITIES.get(priority, PRIORITIES["default"]),
    }
    if tags:
        payload["tags"] = list(tags)
    if click:
        payload["click"] = click
    headers = {}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"

    try:
        response = requests.post(url.rstrip("/") + "/", json=payload,
                                 headers=headers, timeout=TIMEOUT)
    except Exception as e:  # the message would contain the URL
        print(f"[notify] could not send '{title}': {type(e).__name__}")
        return False
    if response.status_code != 200:
        print(f"[notify] could not send '{title}': HTTP {response.status_code}")
        return False
    print(f"[notify] sent ({channel}): {title}")
    return True


def _state_file():
    return os.environ.get("NOTIFY_STATE_FILE") or DEFAULT_STATE_FILE


def load_state():
    try:
        with open(_state_file(), "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[notify] Ignoring unreadable state file: {e}")
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state):
    path = _state_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


@contextlib.contextmanager
def edit_state():
    """Yield the state dict and write it back unless the block raised."""
    state = load_state()
    yield state
    save_state(state)


def _parse_time(value):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _runs(count):
    return f"{count} Fehllauf" if count == 1 else f"{count} Fehlläufe"


def track_failure(key, detail, threshold, *, title=None, channel="alerts",
                  priority="high", remind_every=DEFAULT_REMIND_EVERY):
    """Count one failed run of `key`; alert when the count reaches `threshold`.

    While the failure persists, a reminder goes out at most every
    `remind_every`. Every call site needs a matching track_success(key), or the
    counter never resets and the next single failure alerts at once.
    """
    now = _now()
    with edit_state() as state:
        entry = state.setdefault("failures", {}).setdefault(key, {})
        entry["consecutive"] = entry.get("consecutive", 0) + 1
        entry.setdefault("first_failed_at", now.isoformat())
        entry["last_detail"] = detail
        count = entry["consecutive"]

        title = title or f"Fehler: {key}"
        body = f"{detail}\n\n{_runs(count)} in Folge, seit {entry['first_failed_at']}."
        if count < threshold:
            print(f"[notify] {key}: failure {count} of {threshold} before alerting")
            return
        if not entry.get("alerted_at"):
            if send(channel, title, body, priority=priority, tags=("warning",)):
                entry["alerted_at"] = entry["reminded_at"] = now.isoformat()
            return
        last = _parse_time(entry.get("reminded_at")) or _parse_time(entry.get("alerted_at"))
        if last is None or now - last >= remind_every:
            if send(channel, f"Weiterhin: {title}", body, priority=priority, tags=("warning",)):
                entry["reminded_at"] = now.isoformat()


def track_success(key, *, channel="alerts"):
    """Reset `key`'s failure count; send a recovery note if it had alerted."""
    state = load_state()
    entry = state.get("failures", {}).get(key)
    if not entry:
        return  # nothing to reset: skip the write on the common path
    with edit_state() as state:
        entry = state.get("failures", {}).pop(key, None)
        if entry and entry.get("alerted_at"):
            send(channel, f"Wieder ok: {key}",
                 f"Wieder erfolgreich, zuvor {_runs(entry.get('consecutive', 0))} "
                 f"in Folge seit {entry.get('first_failed_at')}.",
                 priority="low", tags=("white_check_mark",))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("test", help="send a test notification")
    p.add_argument("channel", choices=sorted(DEFAULT_TOPICS))

    p = sub.add_parser("send", help="send one notification")
    p.add_argument("channel", choices=sorted(DEFAULT_TOPICS))
    p.add_argument("title")
    p.add_argument("message")
    p.add_argument("--priority", choices=list(PRIORITIES), default="default")
    p.add_argument("--tag", action="append", default=[], dest="tags")
    p.add_argument("--click")

    p = sub.add_parser("fail", help="count a failed run of KEY")
    p.add_argument("key")
    p.add_argument("detail")
    p.add_argument("--threshold", type=int, default=1)
    p.add_argument("--title")
    p.add_argument("--priority", choices=list(PRIORITIES), default="high")

    p = sub.add_parser("ok", help="reset the failure count of KEY")
    p.add_argument("key")

    sub.add_parser("status", help="print the stored state")

    args = parser.parse_args()
    if args.command == "test":
        ok = send(args.channel, "Test: osm-coverage",
                  f"Testnachricht vom Kanal '{args.channel}' ({_now().isoformat(sep=' ')}). "
                  "Umlaute: äöüß", tags=("test_tube",))
        return 0 if ok else 1
    if args.command == "send":
        ok = send(args.channel, args.title, args.message, priority=args.priority,
                  tags=args.tags, click=args.click)
        return 0 if ok else 1
    # fail/ok run from cron: never fail the pipeline because of a notification
    if args.command == "fail":
        track_failure(args.key, args.detail, args.threshold, title=args.title,
                      priority=args.priority)
    elif args.command == "ok":
        track_success(args.key)
    elif args.command == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
