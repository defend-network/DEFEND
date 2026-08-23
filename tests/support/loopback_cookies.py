"""Loopback Secure-cookie transport policy for local smoke-test clients.

The DEFENDcoder API runs with ``CODER_PUBLIC_HTTPS=true`` (production
behavior): session/CSRF cookies carry the Secure attribute. Modern browsers
treat ``http://127.0.0.1`` and ``http://localhost`` as trustworthy origins
and DO send Secure cookies to loopback, which is how the local web UI
authenticates.

Plain urllib/http.client cookiejars drop Secure cookies on any plain-http
request, including loopback, which breaks local smoke drivers that talk to
the API directly.

This policy mirrors the browser loopback exception and ONLY relaxes the
Secure check for loopback hosts over plain http. Non-loopback hosts keep
the standard Secure-cookie behavior unchanged. It is test/driver support
only — the product never uses it.
"""

from __future__ import annotations

from http.cookiejar import DefaultCookiePolicy

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class LoopbackSecureCookiePolicy(DefaultCookiePolicy):
    """DefaultCookiePolicy that sends Secure cookies to loopback over http."""

    @staticmethod
    def _is_loopback_http(request) -> bool:
        if request.type != "http":
            return False
        host = getattr(request, "host", None) or ""
        hostname = host.split(":", 1)[0].strip("[]").lower()
        return hostname in _LOOPBACK_HOSTS

    def return_ok_secure(self, cookie, request) -> bool:
        if cookie.secure and request.type not in self.secure_protocols:
            if self._is_loopback_http(request):
                return True
            return False
        return True
