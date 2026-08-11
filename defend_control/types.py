from typing import Literal


ModelMode = Literal["vast", "ollama"]
ServiceState = Literal[
    "stopped",
    "validating",
    "provisioning",
    "starting",
    "ready",
    "degraded",
    "stopping",
    "failed",
]
