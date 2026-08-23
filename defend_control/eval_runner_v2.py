"""Compatibility shim -> defend_ai.eval_runner_v2"""

import defend_ai.eval_runner_v2 as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
