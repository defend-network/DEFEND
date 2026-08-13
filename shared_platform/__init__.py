"""Application-neutral boundaries shared by DEFEND and SCS."""

from .application import ApplicationContext, ApplicationId, validate_application_pair
from .secrets import NamespacedSecrets

__all__ = [
    "ApplicationContext",
    "ApplicationId",
    "NamespacedSecrets",
    "validate_application_pair",
]
