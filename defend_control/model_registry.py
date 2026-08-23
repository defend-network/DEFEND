"""Compatibility shim -> defend_ai.model_registry"""

import defend_ai.model_registry as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
