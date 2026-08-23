"""Compatibility shim: migrated to defend_coder.runtime.vast_diagnostics (product-owned runtime).
Re-exports ALL names (including private) for old test/importers."""
import defend_coder.runtime.vast_diagnostics as _impl  # noqa: F401
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
