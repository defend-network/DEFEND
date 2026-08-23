"""Compatibility shim -> defend_ai.eval_runner"""

import defend_ai.eval_runner as _impl
for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
