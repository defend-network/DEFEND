"""Compatibility shim -> shared_platform.secure_store"""

import shared_platform.secure_store as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
