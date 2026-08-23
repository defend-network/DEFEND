"""Compatibility shim: the generic DPAPI secure-persistence primitive moved to
``shared_platform.dpapi``. Old Control Center / integration callers keep
importing from here during the transition; canonical product code imports
``shared_platform.dpapi`` directly.
"""

from shared_platform.dpapi import (  # noqa: F401
    DpapiSecretStore,
    SecretBackend,
    UnsupportedPlatformError,
    WindowsDpapiBackend,
    restrict_to_current_user,
)
