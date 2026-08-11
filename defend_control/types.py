from dataclasses import dataclass
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


@dataclass(frozen=True)
class ModelReady:
    model: str
    backend: str
    endpoint: str
