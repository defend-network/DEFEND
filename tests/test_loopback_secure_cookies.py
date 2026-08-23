"""Regression test for the loopback Secure-cookie smoke-client policy.

Background: the paid live smoke driver authenticates against the product
coder API, which runs with public_https=True so session/CSRF cookies carry
the Secure attribute. A stock urllib cookiejar refuses to SEND Secure
cookies over plain http, so every CSRF-guarded request after login failed
with 401 "invalid session" — even though browsers (the real UI) send
Secure cookies to http://127.0.0.1.

The policy under test must:
- send Secure cookies over plain http to loopback hosts (127.0.0.1, ::1,
  localhost) — mirroring browser behavior,
- NOT relax Secure cookies for non-loopback hosts,
- leave normal https behavior untouched.
"""

from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from urllib.request import Request

from tests.support.loopback_cookies import LoopbackSecureCookiePolicy


def _jar(policy, host: str) -> CookieJar:
    jar = CookieJar(policy=policy)
    jar.set_cookie(
        Cookie(
            version=0,
            name="defendcoder_session",
            value="s3cr3t-s3ss10n",
            port=None,
            port_specified=False,
            domain=host,
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
        )
    )
    return jar


def _header(jar: CookieJar, url: str) -> str:
    request = Request(url)
    jar.add_cookie_header(request)
    return request.get_header("Cookie") or ""


def test_secure_cookie_sent_to_loopback_over_plain_http():
    jar = _jar(LoopbackSecureCookiePolicy(), "127.0.0.1")

    header = _header(jar, "http://127.0.0.1:8301/v1/workspaces")

    assert "defendcoder_session=s3cr3t-s3ss10n" in header


def test_secure_cookie_not_sent_to_non_loopback_over_plain_http():
    jar = _jar(LoopbackSecureCookiePolicy(), "example.com")

    header = _header(jar, "http://example.com/v1/workspaces")

    assert header == ""


def test_secure_cookie_sent_over_https_to_any_host():
    jar = _jar(LoopbackSecureCookiePolicy(), "example.com")

    header = _header(jar, "https://example.com/v1/workspaces")

    assert "defendcoder_session=s3cr3t-s3ss10n" in header


def test_stock_policy_still_drops_secure_cookie_on_loopback_http():
    """Documents the exact bug the policy fixes (and keeps it visible)."""
    jar = _jar(DefaultCookiePolicy(), "127.0.0.1")

    header = _header(jar, "http://127.0.0.1:8301/v1/workspaces")

    assert header == ""
