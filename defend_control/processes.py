"""Compatibility shim -> shared_platform.processes"""

import shared_platform.processes as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
