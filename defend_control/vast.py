"""Compatibility shim -> shared_platform.vast"""

import shared_platform.vast as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
