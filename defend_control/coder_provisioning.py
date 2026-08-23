# ==============================================================
# LEGACY / NON-CANONICAL
# ==============================================================
# STATUS: LEGACY_COMPATIBILITY_SHIM
# RUNTIME_AUTHORITY: NONE
# ==============================================================
LEGACY_COMPATIBILITY_SHIM_ONLY = True
CANONICAL_TARGET = "defend_coder.runtime.provisioning"
"""Compatibility shim: migrated to defend_coder.runtime.provisioning (product-owned runtime).
Re-exports ALL names (including private) for old test/importers."""
import defend_coder.runtime.provisioning as _impl  # noqa: F401
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
