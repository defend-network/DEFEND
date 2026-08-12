from collections.abc import Mapping
from dataclasses import MISSING, asdict, dataclass, fields
from decimal import Decimal, InvalidOperation
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .types import ResourceProfile


_ADAPTER_REPO = "Defend-network/defend-qwen-32b-lora"
_DEFAULT_GPU_FAMILIES = ("A100", "H100", "H200", "B200")
_MIN_GPU_RAM_FLOOR = 140_000


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


def _is_valid_hostname(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    labels = ascii_hostname.split(".")
    return all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )


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
    # Resource policy — floor is hard-enforced at 140 GB
    min_gpu_ram_mb: int = _MIN_GPU_RAM_FLOOR
    allowed_gpu_families: tuple[str, ...] = _DEFAULT_GPU_FAMILIES

    def resource_profile(self) -> ResourceProfile:
        # Always enforce the floor, even if an old settings file had a lower value
        floor = max(self.min_gpu_ram_mb, _MIN_GPU_RAM_FLOOR)
        return ResourceProfile(
            min_gpu_ram_mb=floor,
            allowed_gpu_families=self.allowed_gpu_families,
            num_gpus=1,
            min_reliability=Decimal("0.98"),
            min_disk_gb=self.vllm_disk_gb,
            max_model_len=self.max_model_len,
        )

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
        if any(
            character.isspace()
            or ord(character) < 0x20
            or ord(character) == 0x7F
            for character in public_web_origin
        ):
            raise ValueError("public_web_origin must not contain whitespace")
        try:
            parsed_origin = urlsplit(public_web_origin)
        except ValueError as exc:
            raise ValueError("public_web_origin must contain a valid hostname") from exc
        if parsed_origin.scheme.lower() != "https" or not parsed_origin.netloc:
            raise ValueError("public_web_origin must use HTTPS")
        hostname = parsed_origin.hostname
        if hostname is None or not _is_valid_hostname(hostname):
            raise ValueError("public_web_origin must contain a valid hostname")
        if parsed_origin.netloc.endswith(":"):
            raise ValueError("public_web_origin must contain a valid port")
        try:
            parsed_origin.port
        except ValueError as exc:
            raise ValueError("public_web_origin must contain a valid port") from exc
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

        vllm_image = _string(
            raw.get("vllm_image", "vllm/vllm-openai:v0.10.0"), "vllm_image"
        )
        if vllm_image != "vllm/vllm-openai:v0.10.0":
            raise ValueError("vllm_image must be exactly vllm/vllm-openai:v0.10.0")
        vllm_disk_gb = _positive_int(
            raw.get("vllm_disk_gb", 160), "vllm_disk_gb"
        )
        if vllm_disk_gb != 160:
            raise ValueError("vllm_disk_gb must be exactly 160")
        max_model_len = _positive_int(
            raw.get("max_model_len", 8192), "max_model_len"
        )
        if max_model_len != 8192:
            raise ValueError("max_model_len must be exactly 8192")

        # Always force the 140 GB floor. Old settings files that still contain
        # 80000 (or any lower value) are silently raised.
        requested = raw.get("min_gpu_ram_mb", _MIN_GPU_RAM_FLOOR)
        min_gpu_ram_mb = _positive_int(requested, "min_gpu_ram_mb")
        if min_gpu_ram_mb < _MIN_GPU_RAM_FLOOR:
            min_gpu_ram_mb = _MIN_GPU_RAM_FLOOR

        raw_families = raw.get("allowed_gpu_families", list(_DEFAULT_GPU_FAMILIES))
        if not isinstance(raw_families, (list, tuple)) or not raw_families:
            raise ValueError("allowed_gpu_families must be a non-empty list of strings")
        families: list[str] = []
        for item in raw_families:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("allowed_gpu_families entries must be non-empty strings")
            families.append(item.strip().upper())
        allowed_gpu_families = tuple(dict.fromkeys(families))  # preserve order, dedupe

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
            vllm_image=vllm_image,
            vllm_disk_gb=vllm_disk_gb,
            max_model_len=max_model_len,
            min_gpu_ram_mb=min_gpu_ram_mb,
            allowed_gpu_families=allowed_gpu_families,
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
        # tuples become lists in JSON
        raw["allowed_gpu_families"] = list(raw["allowed_gpu_families"])
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
