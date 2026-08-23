"""Compatibility shim -> defend_ai.deployment_profiles"""

import defend_ai.deployment_profiles as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
