"""Compatibility shim -> defend_ai.qwen3_canary_hosts"""

import defend_ai.qwen3_canary_hosts as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
