# ==============================================================
# LEGACY / NON-CANONICAL
# ==============================================================
# STATUS: LEGACY_COMPATIBILITY_SHIM
# RUNTIME_AUTHORITY: NONE
# ==============================================================
LEGACY_COMPATIBILITY_SHIM_ONLY = True
CANONICAL_TARGET = "shared_platform.vast"
"""Compatibility shim -> shared_platform.vast"""

import shared_platform.vast as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
