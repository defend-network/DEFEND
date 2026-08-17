"""Setup / Integrations control plane backend.

One-way dependency on ``defend_control.redaction`` only (redact_text reuse);
nothing in ``defend_control`` imports this package.
"""

from .models import (
    AdapterKind,
    AdapterProbe,
    AuthType,
    Category,
    HealthBadge,
    Product,
    ProviderConfiguration,
    ProviderDefinition,
    ProviderState,
    mask_secret,
)
from .registry import CATEGORIES, PRODUCTS, PROVIDERS
from .stores import ProviderConfigStore, SecretRegistry, default_config_path
from .service import SetupIntegrationsService

__all__ = [
    "AdapterKind",
    "AdapterProbe",
    "AuthType",
    "CATEGORIES",
    "Category",
    "HealthBadge",
    "PRODUCTS",
    "PROVIDERS",
    "Product",
    "ProviderConfiguration",
    "ProviderConfigStore",
    "ProviderDefinition",
    "ProviderState",
    "SecretRegistry",
    "SetupIntegrationsService",
    "default_config_path",
    "mask_secret",
]