"""TEMPORARY compatibility re-export -> shared_platform.secure_store.

The canonical physical DPAPI secret-persistence implementation is
``shared_platform.secure_store``. This module exists ONLY so early callers that
imported ``shared_platform.dpapi`` keep working during the transition; it adds
no implementation. New code imports ``shared_platform.secure_store`` directly.
"""

from shared_platform.secure_store import (  # noqa: F401
    DpapiSecretStore,
    SecretBackend,
    UnsupportedPlatformError,
    WindowsDpapiBackend,
    restrict_to_current_user,
)
