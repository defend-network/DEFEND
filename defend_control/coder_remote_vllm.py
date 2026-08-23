"""Compatibility shim: migrated to defend_coder.runtime.remote_vllm (product-owned runtime).
Re-exports ALL names (including private) for old test/importers."""
import defend_coder.runtime.remote_vllm as _impl  # noqa: F401
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
