"""Compatibility shim -> defend_ai.qwen3_canary_preflight"""

import defend_ai.qwen3_canary_preflight as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
