"""Compatibility shim -> defend_ai.huggingface"""

import defend_ai.huggingface as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
