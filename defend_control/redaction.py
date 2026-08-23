"""TEMPORARY legacy compatibility shim -> shared_platform.redaction.

The canonical neutral redaction primitive lives in ``shared_platform.redaction``
(see the Platform architecture ledger). Old Control Center callers keep
importing from here during the transition; new code imports
``shared_platform.redaction`` directly. No implementation body lives here.
"""

import shared_platform.redaction as _impl

for _k, _v in vars(_impl).items():
    if not _k.startswith("__"):
        globals()[_k] = _v

del _impl, _k, _v
