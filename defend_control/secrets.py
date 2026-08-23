"""TEMPORARY legacy compatibility re-export -> shared_platform.secure_store.

The canonical physical DPAPI secret-persistence implementation now lives in
``shared_platform.secure_store`` (see the Platform architecture ledger).
Old Control Center / integration callers keep importing from here during the
transition; new code imports ``shared_platform.secure_store`` directly.
No implementation body lives in this module.
"""

from shared_platform.secure_store import (  # noqa: F401
    DpapiSecretStore,
    SecretBackend,
    UnsupportedPlatformError,
    WindowsDpapiBackend,
    restrict_to_current_user,
)
