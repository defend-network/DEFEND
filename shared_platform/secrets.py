from __future__ import annotations

from collections.abc import Iterable, Mapping
import re

from .application import ApplicationContext


_LOGICAL_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class NamespacedSecrets:
    """Read-only logical view over one application's physical secret keys."""

    def __init__(self, values: Mapping[str, str], context: ApplicationContext) -> None:
        if not isinstance(context, ApplicationContext):
            raise TypeError("context must be an ApplicationContext")
        copied = dict(values)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in copied.items()):
            raise ValueError("secret storage must contain string names and values")
        self._values = copied
        self._namespace = context.secret_namespace

    def __repr__(self) -> str:
        return f"NamespacedSecrets(namespace={self._namespace!r})"

    @staticmethod
    def _logical_name(name: object) -> str:
        if not isinstance(name, str) or not _LOGICAL_NAME.fullmatch(name):
            raise ValueError("logical secret name must use uppercase letters, digits, and underscores")
        return name

    def _physical_name(self, logical_name: str) -> str:
        return f"{self._namespace}_{logical_name}"

    def get(self, name: str) -> str | None:
        logical = self._logical_name(name)
        return self._values.get(self._physical_name(logical))

    def export(self, names: Iterable[str]) -> dict[str, str]:
        output: dict[str, str] = {}
        for name in names:
            logical = self._logical_name(name)
            value = self._values.get(self._physical_name(logical))
            if value is None:
                raise KeyError(f"missing logical secret: {logical}")
            output[logical] = value
        return output

    def require(self, *names: str) -> dict[str, str]:
        missing: list[str] = []
        output: dict[str, str] = {}
        for name in names:
            logical = self._logical_name(name)
            value = self._values.get(self._physical_name(logical))
            if value is None or not value:
                missing.append(logical)
            else:
                output[logical] = value
        if missing:
            raise ValueError(f"missing required logical secrets: {', '.join(missing)}")
        return output
