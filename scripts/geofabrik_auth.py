#!/usr/bin/env python3
"""Cookie handling for Geofabrik's internal download server (OpenStreetMap OAuth2 login).

Mirrors oauth_cookie_client.py from geofabrik/sendfile_osm_oauth_protector:

    1. POST /get_cookie?action=get_authorization_url -> Geofabrik's OAuth2
       client_id, state and redirect_uri
    2. log in on openstreetmap.org and submit the authorization form
    3. GET the redirect target with format=http -> the Cookie header value

Configuration via environment (docker compose passes it from deployment/.env):

    GEOFABRIK_OSM_USER, GEOFABRIK_OSM_PASSWORD
        OSM account used for the login. The password is sent in plain text.
    GEOFABRIK_COOKIE_FILE
        Where the cookie is cached between runs. Default: data/.geofabrik_cookie

Without credentials get_download_cookie() returns None and callers use the
public server.

CLI:
    python scripts/geofabrik_auth.py            # show which cookie would be used
    python scripts/geofabrik_auth.py --refresh  # force a fresh login
    python scripts/geofabrik_auth.py --test     # authenticated request against the server
"""

import argparse
import datetime
import os
import re
import sys

import requests

OSM_HOST = "https://www.openstreetmap.org"
PUBLIC_BASE = "https://download.geofabrik.de"
INTERNAL_HOST = "osm-internal.download.geofabrik.de"
INTERNAL_BASE = f"https://{INTERNAL_HOST}"
CONSUMER_URL = f"{INTERNAL_BASE}/get_cookie"
COOKIE_STATUS_URL = f"{INTERNAL_BASE}/cookie_status"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COOKIE_FILE = os.path.join(_REPO_ROOT, "data", ".geofabrik_cookie")
HEADERS = {"User-Agent": "osm-coverage/1.0 (github.com/Tillbtn/osm-coverage)"}
TIMEOUT = 30

# /cookie_status calls a cookie valid until its very last second. A run that
# starts just before the expiry loses the internal server halfway through its
# downloads, so a cookie with less than this left is renewed up front.
COOKIE_MIN_REMAINING = 3600

# Small PBF for a --test request.
TEST_PBF = f"{INTERNAL_BASE}/europe/germany/hamburg-latest-internal.osm.pbf"


class GeofabrikAuthError(RuntimeError):
    """Raised when no usable cookie could be obtained."""


def internal_url(public_url):
    """Internal-server counterpart of a public Geofabrik URL (page or PBF)."""
    return (public_url
            .replace(PUBLIC_BASE, INTERNAL_BASE)
            .replace("-latest.osm.pbf", "-latest-internal.osm.pbf"))


def apply_cookie(session, cookie):
    """Store the cookie in the session's jar.

    A manual 'Cookie' header would be dropped by requests on the redirect that
    '-latest-internal.osm.pbf' goes through; a jar cookie survives it.
    """
    name, _, value = cookie.partition("=")
    session.cookies.set(name.strip(), value.strip(), domain=INTERNAL_HOST, path="/")
    return session


def internal_session(cookie):
    """A requests session that can fetch from the internal server."""
    session = requests.Session()
    session.headers.update(HEADERS)
    apply_cookie(session, cookie)
    return session


def cookie_status(cookie):
    """Ask the server whether a cookie still works.

    Returns the API's JSON dict; 'cookie_status' is one of valid, expired,
    no_cookie_provided, cookie_verification_failed, access_token_use_failed,
    unknown. Network errors are reported as status 'unreachable'.
    """
    try:
        response = internal_session(cookie).get(COOKIE_STATUS_URL, timeout=TIMEOUT)
        return response.json()
    except ValueError:
        return {"cookie_status": "unknown", "description": "no JSON in cookie_status response"}
    except requests.RequestException as e:
        return {"cookie_status": "unreachable", "description": str(e)}


def cookie_expiry(status):
    """/cookie_status's 'valid_until' as an aware datetime, or None if absent."""
    raw = (status or {}).get("valid_until")
    if not raw:
        return None
    try:
        expires = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    return expires


def _remaining(expires):
    """Seconds until the cookie expires, or None when the server did not say."""
    if expires is None:
        return None
    return (expires - datetime.datetime.now(datetime.timezone.utc)).total_seconds()


def describe_validity(expires):
    """How long a cookie is good for, in local time (the logs are local too)."""
    remaining = _remaining(expires)
    if remaining is None:
        return "the server did not say until when"
    local = expires.astimezone().strftime("%Y-%m-%d %H:%M")
    left = f"{remaining / 60:.0f} min" if remaining < 5400 else f"{remaining / 3600:.1f} h"
    return f"{left} left, until {local} local time"


def _cookie_file():
    return os.environ.get("GEOFABRIK_COOKIE_FILE") or DEFAULT_COOKIE_FILE


def read_cached_cookie():
    path = _cookie_file()
    try:
        with open(path, "r") as f:
            cookie = f.read().strip()
    except FileNotFoundError:
        return None
    except OSError as e:
        print(f"[geofabrik] Ignoring unreadable cookie cache {path}: {e}")
        return None
    if "=" not in cookie:
        print(f"[geofabrik] Ignoring cookie cache {path}: not a cookie.")
        return None
    return cookie


def write_cached_cookie(cookie):
    """Cache the cookie for the next run (mode 600)."""
    path = _cookie_file()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(cookie + "\n")


# --------------------------------------------------------------------------
# OAuth2 login
# --------------------------------------------------------------------------

def _authenticity_token(html, what):
    match = re.search(r"name=\"csrf-token\" content=\"([^\"]+)\"", html)
    if not match:
        raise GeofabrikAuthError(
            f"no csrf-token in the {what} page. openstreetmap.org probably changed its forms."
        )
    return match.group(1)


def fetch_cookie(user, password):
    """Log in at openstreetmap.org, authorize Geofabrik's client and return the download cookie."""
    # 1. Geofabrik hands out its own OAuth2 client parameters.
    response = requests.post(
        CONSUMER_URL, params={"action": "get_authorization_url"},
        headers=HEADERS, timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise GeofabrikAuthError(
            f"get_authorization_url returned HTTP {response.status_code}"
        )
    try:
        params = response.json()
        authorization_url = params["authorization_url"]
        state = params["state"]
        redirect_uri = params["redirect_uri"]
        client_id = params["client_id"]
    except (ValueError, KeyError) as e:
        raise GeofabrikAuthError(f"unexpected get_authorization_url response: {e}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # 2. Log in to openstreetmap.org (scraping its form, as JOSM does).
    login_page = session.get(f"{OSM_HOST}/login?cookie_test=true", timeout=TIMEOUT)
    if login_page.status_code != 200:
        raise GeofabrikAuthError(f"GET /login returned HTTP {login_page.status_code}")

    response = session.post(
        f"{OSM_HOST}/login",
        data={
            "username": user,
            "password": password,
            "referer": "/",
            "commit": "Login",
            "authenticity_token": _authenticity_token(login_page.text, "login"),
        },
        allow_redirects=False, timeout=TIMEOUT,
    )
    if response.status_code != 302:
        raise GeofabrikAuthError(
            f"OSM login returned HTTP {response.status_code} instead of 302: "
            "wrong user/password, or the account needs attention on openstreetmap.org"
        )

    # 3. Authorize Geofabrik's app. Already-authorized accounts skip the form.
    response = session.get(authorization_url, allow_redirects=False, timeout=TIMEOUT)
    if response.status_code == 200:
        response = session.post(
            authorization_url,
            data={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "authenticity_token": _authenticity_token(response.text, "authorization"),
                "state": state,
                "response_type": "code",
                "scope": "read_prefs",
                "nonce": "",
                "code_challenge": "",
                "code_challenge_method": "",
                "commit": "Authorize",
            },
            allow_redirects=False, timeout=TIMEOUT,
        )
    if response.status_code != 302:
        raise GeofabrikAuthError(
            f"OAuth2 authorization returned HTTP {response.status_code} instead of 302"
        )
    location = response.headers.get("location", "")
    if "?" not in location:
        raise GeofabrikAuthError("authorization redirect carried no query string")

    # End the OSM session; only the Geofabrik cookie is kept.
    try:
        session.get(f"{OSM_HOST}/logout", timeout=TIMEOUT)
    except requests.RequestException:
        pass

    # 4. Trade the authorization code for the download cookie.
    response = requests.get(f"{location}&format=http", headers=HEADERS, timeout=TIMEOUT)
    if response.status_code != 200:
        raise GeofabrikAuthError(
            f"get_access_token_cookie returned HTTP {response.status_code}"
        )
    cookie = response.text.strip().splitlines()[0].strip() if response.text.strip() else ""
    if "=" not in cookie:
        raise GeofabrikAuthError(f"get_access_token_cookie returned no cookie: {cookie[:40]!r}")
    return cookie


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

_MEMO = {}


def resolve_cookie(force_refresh=False):
    """Return a cookie the server accepts, or None without credentials.

    Uses the cached cookie if /cookie_status reports it valid, otherwise logs in.
    """
    if not force_refresh:
        cookie = read_cached_cookie()
        if cookie:
            status = cookie_status(cookie)
            state = status.get("cookie_status")
            expires = cookie_expiry(status)
            remaining = _remaining(expires)
            if state == "valid" and (remaining is None or remaining >= COOKIE_MIN_REMAINING):
                print(f"[geofabrik] Using cached cookie ({describe_validity(expires)}).")
                return cookie
            if state == "valid":
                print(f"[geofabrik] Cached cookie expires too soon "
                      f"({describe_validity(expires)}); logging in again.")
            else:
                print(f"[geofabrik] Cached cookie is not usable "
                      f"({state}: {status.get('description')}).")

    user = os.environ.get("GEOFABRIK_OSM_USER")
    password = os.environ.get("GEOFABRIK_OSM_PASSWORD")
    if not user:
        print("[geofabrik] GEOFABRIK_OSM_USER/GEOFABRIK_OSM_PASSWORD not set. "
              "Using the public download server.")
        return None
    print("[geofabrik] Requesting a new download cookie...")
    cookie = fetch_cookie(user, password)
    try:
        write_cached_cookie(cookie)
    except OSError as e:
        print(f"[geofabrik] Warning: could not cache the cookie: {e}")
    return cookie


def refresh_download_cookie():
    """One fresh login per process, for callers the server just turned away.

    The internal server answers a stale cookie with HTTP 200 and an HTML login
    page, so an expiry that happens mid-run only shows up in a response body.
    Returns the new cookie, or None without credentials, after a failed login,
    or when this process already refreshed once (a genuinely rejected account
    must not cause one login attempt per state).
    """
    if _MEMO.get("refreshed"):
        return None
    _MEMO["refreshed"] = True
    return get_download_cookie(force_refresh=True)


def get_download_cookie(force_refresh=False):
    """resolve_cookie(), cached per process.

    Returns None instead of raising so callers fall back to the public server.
    """
    if force_refresh or "cookie" not in _MEMO:
        try:
            _MEMO["cookie"] = resolve_cookie(force_refresh)
        except (GeofabrikAuthError, requests.RequestException) as e:
            print(f"[geofabrik] Login failed: {e}")
            print("[geofabrik] Falling back to the public download server.")
            _MEMO["cookie"] = None
    return _MEMO["cookie"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_test(cookie):
    """HEAD the test PBF with the cookie and check whether a .md5 is published."""
    session = internal_session(cookie)
    try:
        response = session.head(TEST_PBF, allow_redirects=True, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"FAIL  {TEST_PBF}: {e}")
        return 1
    if response.status_code != 200:
        print(f"FAIL  HTTP {response.status_code} for {TEST_PBF}")
        print("      (403 means the cookie was not accepted)")
        return 1
    size = int(response.headers.get("Content-Length", 0))
    print(f"OK    HTTP 200, {size / 1048576:.1f} MB, final URL {response.url}")
    print(f"      Last-Modified: {response.headers.get('Last-Modified')}")

    md5 = session.get(TEST_PBF + ".md5", timeout=TIMEOUT)
    token = md5.text.strip().split()[0].lower() if md5.ok and md5.text.strip() else ""
    if re.fullmatch(r"[0-9a-f]{32}", token):
        print(f"OK    .md5 published ({token})")
    else:
        print(f"WARN  no usable .md5 (HTTP {md5.status_code}). "
              "Internal downloads will only be size-checked.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cached cookie and log in again")
    parser.add_argument("--test", action="store_true",
                        help="try an authenticated request against the internal server")
    args = parser.parse_args()

    try:
        cookie = resolve_cookie(force_refresh=args.refresh)
    except (GeofabrikAuthError, requests.RequestException) as e:
        print(f"[geofabrik] Login failed: {e}")
        return 1
    if not cookie:
        print("[geofabrik] No cookie available; the pipeline would use the public server.")
        return 1

    status = cookie_status(cookie)
    print(f"[geofabrik] Cookie status: {status.get('cookie_status')} "
          f"({describe_validity(cookie_expiry(status))}), cached in {_cookie_file()}")
    if args.test:
        return _cmd_test(cookie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
