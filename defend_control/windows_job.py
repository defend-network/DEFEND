"""Compatibility shim -> shared_platform.windows_job"""

import shared_platform.windows_job as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
