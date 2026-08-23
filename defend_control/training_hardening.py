"""Compatibility shim -> defend_ai.training_hardening"""

import defend_ai.training_hardening as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
