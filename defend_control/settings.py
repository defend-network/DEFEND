from collections.abc import Mapping
from dataclasses import MISSING, asdict, dataclass, fields
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


_ADAPTER_REPO = "Defend-network/defend-qwen-32b-lora"


def _string(raw: object, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return raw


def _path(raw: object, name: str) -> Path:
    if not isinstance(raw, (str, os.PathLike)):
        raise ValueError(f"{name} must be a filesystem path")
    return Path(raw)


def _port(raw: object, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{name} port must be an integer")
    if not 1 <= raw <= 65_535:
        raise ValueError(f"{name} port must be in 1..65535")
    return raw


def _positive_int(raw: object, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return raw


@dataclass(frozen=True)
class ControlSettings:
    repo_root: Path
    data_root: Path
    public_web_origin: str
    cloudflared_exe: Path
    cloudflared_config: Path
    cloudflared_tunnel: str
    adapter_repo: str
    local_model: str
    vast_max_hourly: Decimal
    api_port: int = 8000
    web_port: int = 3000
    model_port: int = 8001
    vllm_image: str = "vllm/vllm-openai:v0.10.0"
    vllm_disk_gb: int = 160
    max_model_len: int = 8192

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "ControlSettings":
        allowed = {field.name for field in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            names = ", ".join(sorted(repr(name) for name in unknown))
            raise ValueError(f"unknown settings keys: {names}")

        required = {
            field.name
            for field in fields(cls)
            if field.default is MISSING and field.default_factory is MISSING
        }
        missing = required - set(raw)
        if missing:
            raise ValueError(f"missing settings keys: {', '.join(sorted(missing))}")

        repo_root = _path(raw["repo_root"], "repo_root")
        if not repo_root.is_absolute():
            raise ValueError("repo_root must be absolute")
        if not repo_root.is_dir():
            raise ValueError("repo_root must be an existing directory")

        public_web_origin = _string(raw["public_web_origin"], "public_web_origin")
        parsed_origin = urlsplit(public_web_origin)
        if parsed_origin.scheme.lower() != "https" or not parsed_origin.netloc:
            raise ValueError("public_web_origin must use HTTPS")
        if (
            parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.path not in ("", "/")
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise ValueError("public_web_origin must be an HTTPS origin without a path")

        adapter_repo = _string(raw["adapter_repo"], "adapter_repo")
        if adapter_repo != _ADAPTER_REPO:
            raise ValueError(f"adapter_repo must be exactly {_ADAPTER_REPO}")

        price_raw = raw["vast_max_hourly"]
        if isinstance(price_raw, bool) or not isinstance(
            price_raw, (str, int, Decimal)
        ):
            raise ValueError("vast_max_hourly must be a decimal value")
        try:
            vast_max_hourly = Decimal(str(price_raw))
        except InvalidOperation as exc:
            raise ValueError("vast_max_hourly must be a decimal value") from exc
        if not vast_max_hourly.is_finite():
            raise ValueError("vast_max_hourly must be finite")
        if vast_max_hourly <= 0:
            raise ValueError("vast_max_hourly must be positive")

        api_port = _port(raw.get("api_port", 8000), "api_port")
        web_port = _port(raw.get("web_port", 3000), "web_port")
        model_port = _port(raw.get("model_port", 8001), "model_port")
        if len({api_port, web_port, model_port}) != 3:
            raise ValueError("api_port, web_port, and model_port must be unique")

        return cls(
            repo_root=repo_root,
            data_root=_path(raw["data_root"], "data_root"),
            public_web_origin=public_web_origin,
            cloudflared_exe=_path(raw["cloudflared_exe"], "cloudflared_exe"),
            cloudflared_config=_path(
                raw["cloudflared_config"], "cloudflared_config"
            ),
            cloudflared_tunnel=_string(
                raw["cloudflared_tunnel"], "cloudflared_tunnel"
            ),
            adapter_repo=adapter_repo,
            local_model=_string(raw["local_model"], "local_model"),
            vast_max_hourly=vast_max_hourly,
            api_port=api_port,
            web_port=web_port,
            model_port=model_port,
            vllm_image=_string(
                raw.get("vllm_image", "vllm/vllm-openai:v0.10.0"), "vllm_image"
            ),
            vllm_disk_gb=_positive_int(
                raw.get("vllm_disk_gb", 160), "vllm_disk_gb"
            ),
            max_model_len=_positive_int(
                raw.get("max_model_len", 8192), "max_model_len"
            ),
        )


class JsonSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def load(self) -> ControlSettings:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("settings file is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError("settings file must contain a JSON object")
        return ControlSettings.from_mapping(raw)

    def save(self, settings: ControlSettings) -> None:
        raw = asdict(settings)
        for name in (
            "repo_root",
            "data_root",
            "cloudflared_exe",
            "cloudflared_config",
        ):
            raw[name] = str(raw[name])
        raw["vast_max_hourly"] = str(raw["vast_max_hourly"])
        encoded = (json.dumps(raw, indent=2, sort_keys=True) + "\n").encode("utf-8")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)
