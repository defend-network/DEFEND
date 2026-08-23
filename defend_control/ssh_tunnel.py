"""Compatibility shim: migrated to shared_platform.ssh_tunnel (product-owned runtime).
Re-exports ALL names (including private) for old test/importers."""
import shared_platform.ssh_tunnel as _impl  # noqa: F401
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
