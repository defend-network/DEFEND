"""Application-neutral boundaries shared by DEFEND and SCS."""

from .application import ApplicationContext, ApplicationId, validate_application_pair

__all__ = ["ApplicationContext", "ApplicationId", "validate_application_pair"]
