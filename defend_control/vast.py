from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import random
import re
import time
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .types import LaunchSpec, ResourceProfile, VastInstance, VastOffer


_API_ROOT = "https://console.vast.ai/api/v0"
_API_V1_ROOT = "https://console.vast.ai/api/v1"
_MAX_RESPONSE_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 30.0
_MAX_ATTEMPTS = 3
_PROVISIONING_TIMEOUT_SECONDS = 300.0
_DESTRUCTION_VERIFY_SECONDS = 30.0
_DESTRUCTION_POLL_SECONDS = 2.0
_PENDING_STATUSES = frozenset(
    {
        None,
        "created",
        "loading",
        "scheduling",
        "starting",
        "rebooting",
        "restarting",
    }
)
_TERMINAL_STATUSES = frozenset({"exited", "unknown", "offline"})

# Default profile used when callers do not supply one (higher floor + modern families)
_DEFAULT_PROFILE = ResourceProfile()


class VastError(RuntimeError):
    """A safe Vast.ai failure containing no provider body or credential data."""


class VastOfferUnavailable(VastError):
    """Raised when an offer becomes unavailable before instance creation."""


class VastSchedulingTimeout(VastError):
    """Raised when a confirmed restart cannot regain scheduled compute."""

    def __init__(self, instance_id: int) -> None:
        super().__init__("Vast.ai restart remained scheduled for 30 seconds")
        self.instance_id = instance_id


class _DeadlineExceeded(Exception):
    pass


@dataclass(frozen=True)
class _Response:
    status_code: int
    body: bytes


class _Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):
        return None


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response:
        payload = None
        if json is not None:
            payload = globals()["json"].dumps(
                json, separators=(",", ":")
            ).encode("utf-8")
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(max_response_bytes + 1)
                status_code = int(getattr(response, "status", 200))
        except HTTPError as error:
            body = error.read(max_response_bytes + 1)
            status_code = int(error.code)
        if len(body) > max_response_bytes:
            raise ValueError("response exceeds 64 KiB")
        return _Response(status_code, body)


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} is invalid") from None
    if not result.is_finite():
        raise ValueError(f"{field} is invalid")
    return result


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or type(value) is not int or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def _gpu_name_matches(gpu_name: str, families: tuple[str, ...]) -> bool:
    """Return True when the GPU name starts with any allowed family."""
    normalized = gpu_name.strip().upper()
    for family in families:
        if normalized.startswith(family.upper()):
            return True
    return False


class VastClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: _Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("Vast.ai API key must be a non-empty string")
        self._api_key = api_key
        self._transport = transport or _UrllibTransport()
        self._sleep = sleep
        self._jitter = jitter
        self._monotonic = monotonic
        self._offer_search_summary = "search not run"

    def __repr__(self) -> str:
        return "VastClient()"

    @property
    def offer_search_summary(self) -> str:
        return self._offer_search_summary

    def search_offers(
        self,
        max_hourly: Decimal,
        profile: ResourceProfile | None = None,
    ) -> tuple[VastOffer, ...]:
        ceiling = _decimal(max_hourly, "maximum hourly price")
        if ceiling <= 0:
            raise ValueError("maximum hourly price must be positive")
        policy = profile if profile is not None else _DEFAULT_PROFILE
        document = self._request_json(
            "POST",
            f"{_API_ROOT}/bundles/",
            {
                "type": "on-demand",
                "verified": {"eq": True},
                "rentable": {"eq": True},
                "rented": {"eq": False},
                "num_gpus": {"eq": policy.num_gpus},
                "gpu_ram": {"gte": policy.min_gpu_ram_mb},
                "disk_space": {"gte": policy.min_disk_gb},
                "direct_port_count": {"gte": 1},
                "reliability": {"gte": float(policy.min_reliability)},
                "dph_total": {"lte": float(ceiling)},
                "allocated_storage": policy.min_disk_gb,
                "order": [["dph_total", "asc"]],
                "limit": 20,
            },
        )
        raw_offers = document.get("offers") if isinstance(document, Mapping) else None
        if not isinstance(raw_offers, list):
            raise VastError("Vast.ai offer response is invalid")
        offers: list[VastOffer] = []
        for raw in raw_offers:
            offer = self._validated_offer(raw, ceiling, policy)
            if offer is not None:
                offers.append(offer)
        offers.sort(key=lambda offer: (offer.dph_total, offer.offer_id))
        self._offer_search_summary = (
            f"provider returned {len(raw_offers)}; eligible {len(offers)}"
        )
        return tuple(offers[:20])

    def list_labeled_instance_ids(self, label: str) -> tuple[int, ...]:
        if (
            not isinstance(label, str)
            or not label
            or len(label) > 128
            or any(ord(character) < 0x20 for character in label)
        ):
            raise ValueError("Vast.ai instance label is invalid")
        filters = json.dumps(
            {"label": {"eq": label}}, separators=(",", ":")
        )
        query = urlencode({"limit": 25, "select_filters": filters})
        document = self._request_json(
            "GET", f"{_API_V1_ROOT}/instances/?{query}", None
        )
        candidates = document.get("instances") if isinstance(document, Mapping) else None
        instances_found = (
            document.get("instances_found") if isinstance(document, Mapping) else None
        )
        total_instances = (
            document.get("total_instances") if isinstance(document, Mapping) else None
        )
        if (
            not isinstance(document, Mapping)
            or document.get("success") is not True
            or not isinstance(candidates, list)
            or type(instances_found) is not int
            or type(total_instances) is not int
            or instances_found != len(candidates)
            or total_instances != len(candidates)
            or len(candidates) > 25
            or document.get("next_token") is not None
        ):
            raise VastError("Vast.ai instance list response is invalid")
        instance_ids: list[int] = []
        for candidate in candidates:
            if not isinstance(candidate, Mapping) or candidate.get("label") != label:
                continue
            try:
                instance_ids.append(
                    _positive_int(candidate.get("id"), "instance ID")
                )
            except ValueError:
                raise VastError("Vast.ai instance list response is invalid") from None
        if len(set(instance_ids)) != len(instance_ids):
            raise VastError("Vast.ai instance list response is invalid")
        return tuple(instance_ids)

    def create_instance(self, offer: VastOffer, launch: LaunchSpec) -> VastInstance:
        if not isinstance(offer, VastOffer):
            raise ValueError("offer must be a VastOffer")
        if launch != LaunchSpec.default():
            raise ValueError("only the approved DEFEND Vast launch is supported")
        offer_id = _positive_int(offer.offer_id, "offer ID")
        document = self._request_json(
            "PUT",
            f"{_API_ROOT}/asks/{offer_id}/",
            {
                "client_id": "me",
                "image": launch.image,
                "env": {},
                "disk": launch.disk_gb,
                "runtype": launch.runtype,
                "target_state": "running",
                "cancel_unavail": True,
                "label": launch.label,
                "onstart": None,
                "image_login": None,
                "python_utf8": False,
                "lang_utf8": False,
                "use_jupyter_lab": False,
                "jupyter_dir": None,
                "force": False,
                "template_hash_id": None,
                "user": None,
            },
            offer_race=True,
            retry_429=False,
        )
        instance_id = None
        if isinstance(document, Mapping):
            if document.get("success") is not True:
                raise VastOfferUnavailable("Vast.ai offer is no longer rentable")
            instance_id = document.get("new_contract", document.get("id"))
        try:
            parsed_id = _positive_int(instance_id, "instance ID")
        except ValueError:
            raise VastError("Vast.ai create response is invalid") from None
        return VastInstance(
            parsed_id,
            None,
            None,
            None,
            offer.gpu_name,
            offer.gpu_ram_mb,
            offer.dph_total,
        )

    def show_instance(
        self,
        instance_id: int,
        *,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        deadline: float | None = None,
    ) -> VastInstance:
        parsed_id = _positive_int(instance_id, "instance ID")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= _TIMEOUT_SECONDS
        ):
            raise ValueError("Vast.ai request timeout is invalid")
        raw = self._instance_payload(
            parsed_id,
            timeout_seconds=float(timeout_seconds),
            deadline=deadline,
        )
        try:
            return self._parse_instance(raw, parsed_id)
        except ValueError:
            raise VastError("Vast.ai instance response is invalid") from None

    def _instance_payload(
        self,
        instance_id: int,
        *,
        timeout_seconds: float,
        deadline: float | None,
    ) -> Mapping[str, object]:
        document = self._request_json(
            "GET",
            f"{_API_ROOT}/instances/{instance_id}/",
            None,
            timeout_seconds=timeout_seconds,
            deadline=deadline,
        )
        raw: object = document
        if isinstance(document, Mapping) and "instances" in document:
            candidates = document.get("instances")
            if isinstance(candidates, Mapping):
                raw = candidates
            elif isinstance(candidates, list):
                raw = next(
                    (
                        candidate
                        for candidate in candidates
                        if isinstance(candidate, Mapping)
                        and candidate.get("id") == instance_id
                    ),
                    None,
                )
            else:
                raise VastError("Vast.ai instance response is invalid")
        if not isinstance(raw, Mapping):
            raise VastError("Vast.ai instance response is invalid") from None
        raw_id = raw.get("id")
        if raw_id is not None:
            try:
                if _positive_int(raw_id, "instance ID") != instance_id:
                    raise ValueError("instance ID does not match")
            except ValueError:
                raise VastError("Vast.ai instance response is invalid") from None
        return raw

    def set_state(self, instance_id: int, state: str) -> bool:
        parsed_id = _positive_int(instance_id, "instance ID")
        if state not in ("running", "stopped"):
            raise ValueError("Vast.ai instance state must be running or stopped")
        response = self._request(
            "PUT", f"{_API_ROOT}/instances/{parsed_id}/", {"state": state}
        )
        self._require_mutation_success(response, "Vast.ai state change failed")
        return True

    def destroy_instance(
        self,
        instance_id: int,
        *,
        confirmed_instance_id: int | None = None,
    ) -> bool:
        parsed_id = _positive_int(instance_id, "instance ID")
        if (
            isinstance(confirmed_instance_id, bool)
            or type(confirmed_instance_id) is not int
            or confirmed_instance_id != parsed_id
        ):
            raise ValueError("destruction requires the exact instance ID")
        response = self._request(
            "DELETE", f"{_API_ROOT}/instances/{parsed_id}/", None
        )
        self._require_mutation_success(response, "Vast.ai destruction failed")
        self._wait_until_destroyed(parsed_id)
        return True

    def _wait_until_destroyed(self, instance_id: int) -> None:
        deadline = self._monotonic() + _DESTRUCTION_VERIFY_SECONDS
        url = f"{_API_ROOT}/instances/{instance_id}/"
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise VastError(
                    "Vast.ai destruction could not be verified after 30 seconds"
                )
            try:
                response = self._request(
                    "GET",
                    url,
                    None,
                    timeout_seconds=min(_TIMEOUT_SECONDS, remaining),
                    deadline=deadline,
                    allow_not_found=True,
                )
            except _DeadlineExceeded:
                raise VastError(
                    "Vast.ai destruction could not be verified after 30 seconds"
                ) from None
            if response.status_code == 404:
                return
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise VastError(
                    "Vast.ai destruction could not be verified after 30 seconds"
                )
            self._sleep(min(_DESTRUCTION_POLL_SECONDS, remaining))

    def ensure_account_ssh_key(self, public_key: str) -> int:
        if (
            not isinstance(public_key, str)
            or not public_key
            or "\n" in public_key
            or "\r" in public_key
            or len(public_key.encode("utf-8")) > 16 * 1024
        ):
            raise ValueError("dedicated SSH public key is invalid")
        document = self._request_json("GET", f"{_API_ROOT}/ssh/", None)
        existing_id = self._find_ssh_key_id(document, public_key)
        if existing_id is not None:
            return existing_id
        response = self._request(
            "POST",
            f"{_API_ROOT}/ssh/",
            {"ssh_key": public_key},
            retry_429=False,
        )
        created = self._require_mutation_success(
            response, "Vast.ai SSH key creation failed"
        )
        if created is None:
            reconciled = self._request_json("GET", f"{_API_ROOT}/ssh/", None)
            reconciled_id = self._find_ssh_key_id(reconciled, public_key)
            if reconciled_id is None:
                raise VastError("Vast.ai SSH key response is invalid")
            return reconciled_id
        created_id = created.get("id", created.get("ssh_key_id"))
        nested_key = created.get("key")
        if created_id is None and isinstance(nested_key, Mapping):
            created_id = nested_key.get("id")
        try:
            return _positive_int(created_id, "SSH key ID")
        except ValueError:
            raise VastError("Vast.ai SSH key response is invalid") from None

    @staticmethod
    def _find_ssh_key_id(document: object, public_key: str) -> int | None:
        requested_identity = VastClient._canonical_ssh_key(public_key)
        candidates: object = document
        if isinstance(document, Mapping):
            candidates = document.get("ssh_keys", document.get("keys"))
        if not isinstance(candidates, list):
            raise VastError("Vast.ai SSH key response is invalid")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            existing_key = candidate.get(
                "ssh_key", candidate.get("public_key", candidate.get("key"))
            )
            try:
                existing_identity = (
                    VastClient._canonical_ssh_key(existing_key)
                    if isinstance(existing_key, str)
                    else None
                )
            except ValueError:
                continue
            if existing_identity == requested_identity:
                try:
                    return _positive_int(candidate.get("id"), "SSH key ID")
                except ValueError:
                    raise VastError("Vast.ai SSH key response is invalid") from None
        return None

    @staticmethod
    def _canonical_ssh_key(public_key: str) -> tuple[str, str]:
        fields = public_key.strip().split()
        if len(fields) < 2:
            raise ValueError("dedicated SSH public key is invalid")
        algorithm, blob = fields[:2]
        if (
            algorithm != "ssh-ed25519"
            or not blob
            or not all(
                character.isalnum() or character in "+/=" for character in blob
            )
        ):
            raise ValueError("dedicated SSH public key is invalid")
        return algorithm, blob

    @staticmethod
    def _require_mutation_success(
        response: _Response, safe_error: str
    ) -> Mapping[str, object] | None:
        if not response.body:
            if response.status_code == 204:
                return None
            raise VastError(safe_error)
        try:
            document = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise VastError(safe_error) from None
        if not isinstance(document, Mapping) or document.get("success") is not True:
            raise VastError(safe_error)
        return document

    def wait_until_running(
        self,
        instance_id: int,
        *,
        timeout_seconds: float = _PROVISIONING_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 10.0,
        allow_stopped_transition: bool = False,
        scheduling_timeout_seconds: float | None = None,
    ) -> VastInstance:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or float(timeout_seconds) != _PROVISIONING_TIMEOUT_SECONDS
        ):
            raise ValueError("Vast.ai provisioning timeout must be 300 seconds")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or float(poll_interval_seconds) < 0
            or float(poll_interval_seconds) > 30
        ):
            raise ValueError("Vast.ai polling interval is invalid")
        if type(allow_stopped_transition) is not bool:
            raise ValueError("Vast.ai stopped-transition option is invalid")
        if scheduling_timeout_seconds is not None and (
            not allow_stopped_transition
            or isinstance(scheduling_timeout_seconds, bool)
            or not isinstance(scheduling_timeout_seconds, (int, float))
            or float(scheduling_timeout_seconds) != 30.0
        ):
            raise ValueError("Vast.ai scheduling timeout must be 30 seconds")
        parsed_id = _positive_int(instance_id, "instance ID")
        deadline = self._monotonic() + _PROVISIONING_TIMEOUT_SECONDS
        scheduling_deadline: float | None = None
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise VastError("Vast.ai provisioning timed out after 300 seconds")
            try:
                raw = self._instance_payload(
                    parsed_id,
                    timeout_seconds=min(_TIMEOUT_SECONDS, remaining),
                    deadline=deadline,
                )
            except _DeadlineExceeded:
                raise VastError(
                    "Vast.ai provisioning timed out after 300 seconds"
                ) from None
            after_response = self._monotonic()
            if after_response >= deadline:
                raise VastError("Vast.ai provisioning timed out after 300 seconds")
            status = raw.get("actual_status")
            if status is not None and not isinstance(status, str):
                raise VastError("Vast.ai instance response is invalid")
            if status == "running":
                try:
                    return self._parse_instance(raw, parsed_id)
                except ValueError:
                    raise VastError("Vast.ai instance response is invalid") from None
            if status == "scheduling" and scheduling_timeout_seconds is not None:
                if scheduling_deadline is None:
                    scheduling_deadline = (
                        after_response + float(scheduling_timeout_seconds)
                    )
                if after_response >= scheduling_deadline:
                    raise VastSchedulingTimeout(parsed_id)
            elif status != "scheduling":
                scheduling_deadline = None
            pending_statuses = _PENDING_STATUSES
            if allow_stopped_transition:
                pending_statuses = pending_statuses | {"stopped", "exited"}
            if status not in pending_statuses:
                safe_status = (
                    status
                    if status in _TERMINAL_STATUSES
                    else "unrecognized"
                )
                raise VastError(
                    "Vast.ai provisioning failed "
                    f"(terminal status {safe_status})"
                )
            remaining = deadline - after_response
            if scheduling_deadline is not None:
                remaining = min(remaining, scheduling_deadline - after_response)
            self._sleep(min(float(poll_interval_seconds), remaining))

    @staticmethod
    def billing_warning(instance: VastInstance) -> str | None:
        if not isinstance(instance, VastInstance):
            raise ValueError("instance must be a VastInstance")
        if instance.actual_status == "stopped":
            return "Instance is stopped; disk charges may continue until destruction."
        return None

    @staticmethod
    def _validated_offer(
        raw: object,
        ceiling: Decimal,
        profile: ResourceProfile,
    ) -> VastOffer | None:
        if not isinstance(raw, Mapping):
            return None
        try:
            if "verified" in raw:
                verified = raw.get("verified") is True
            else:
                verification = raw.get("verification")
                verified = (
                    isinstance(verification, str)
                    and verification.strip().casefold() == "verified"
                )
            if "type" in raw:
                on_demand = raw.get("type") in ("on-demand", "ondemand")
            else:
                on_demand = raw.get("is_bid") is False
            if (
                not verified
                or raw.get("rentable") is not True
                or raw.get("rented") is not False
                or not on_demand
                or type(raw.get("num_gpus")) is not int
                or raw.get("num_gpus") != profile.num_gpus
            ):
                return None
            gpu_ram = _positive_int(raw.get("gpu_ram"), "GPU RAM")
            if gpu_ram < profile.min_gpu_ram_mb:
                return None
            disk_space = _decimal(raw.get("disk_space"), "disk space")
            if disk_space < profile.min_disk_gb:
                return None
            dph_total = _decimal(raw.get("dph_total"), "hourly price")
            if dph_total < 0 or dph_total > ceiling:
                return None
            offer_id = _positive_int(raw.get("id"), "offer ID")
            gpu_name = raw.get("gpu_name")
            if not isinstance(gpu_name, str) or not _gpu_name_matches(
                gpu_name, profile.allowed_gpu_families
            ):
                return None
            reliability = _decimal(
                raw.get("reliability", raw.get("reliability2")), "reliability"
            )
            if reliability < profile.min_reliability or reliability > 1:
                return None
            storage_cost = (
                None
                if raw.get("storage_cost") is None
                else _decimal(raw.get("storage_cost"), "storage cost")
            )
            storage_total = (
                None
                if raw.get("storage_total_cost") is None
                else _decimal(raw.get("storage_total_cost"), "storage total cost")
            )
            if (
                storage_cost is not None
                and storage_cost < 0
                or storage_total is not None
                and storage_total < 0
            ):
                return None
        except ValueError:
            return None
        return VastOffer(
            offer_id,
            gpu_name,
            gpu_ram,
            dph_total,
            reliability,
            storage_cost,
            storage_total,
        )

    @staticmethod
    def _parse_instance(raw: object, expected_id: int) -> VastInstance:
        if not isinstance(raw, Mapping):
            raise ValueError("instance is invalid")
        instance_id = _positive_int(raw.get("id"), "instance ID")
        if instance_id != expected_id:
            raise ValueError("instance ID does not match")
        status = raw.get("actual_status")
        if status is not None and not isinstance(status, str):
            raise ValueError("actual status is invalid")
        ssh_host = raw.get("ssh_host")
        if ssh_host is not None and (
            not isinstance(ssh_host, str) or not ssh_host
        ):
            raise ValueError("SSH host is invalid")
        ssh_port = raw.get("ssh_port")
        if ssh_port is not None:
            ssh_port = _positive_int(ssh_port, "SSH port")
        gpu_name = raw.get("gpu_name")
        if not isinstance(gpu_name, str) or not gpu_name:
            raise ValueError("GPU name is invalid")
        gpu_ram = _positive_int(raw.get("gpu_ram"), "GPU RAM")
        dph_total = _decimal(raw.get("dph_total"), "hourly price")
        if dph_total < 0:
            raise ValueError("hourly price is invalid")
        return VastInstance(
            instance_id,
            status,
            ssh_host,
            ssh_port,
            gpu_name,
            gpu_ram,
            dph_total,
        )

    def _request(
        self,
        method: str,
        url: str,
        body: object | None,
        *,
        offer_race: bool = False,
        retry_429: bool = True,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        deadline: float | None = None,
        allow_not_found: bool = False,
    ) -> _Response:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        response: _Response | None = None
        max_attempts = _MAX_ATTEMPTS if retry_429 else 1
        for attempt in range(max_attempts):
            attempt_timeout = timeout_seconds
            if deadline is not None:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise _DeadlineExceeded
                attempt_timeout = min(attempt_timeout, remaining)
            try:
                response = self._transport.request(
                    method,
                    url,
                    headers=headers,
                    json=body,
                    timeout=attempt_timeout,
                    max_response_bytes=_MAX_RESPONSE_BYTES,
                )
            except Exception as error:
                if deadline is not None and self._monotonic() >= deadline:
                    raise _DeadlineExceeded from None
                raise VastError(
                    f"Vast.ai request failed ({type(error).__name__})"
                ) from None
            if deadline is not None and self._monotonic() >= deadline:
                raise _DeadlineExceeded
            if len(response.body) > _MAX_RESPONSE_BYTES:
                raise VastError("Vast.ai response exceeds 64 KiB")
            if response.status_code != 429 or attempt == max_attempts - 1:
                break
            try:
                jitter = float(self._jitter())
            except Exception:
                jitter = 0.0
            jitter = min(1.0, max(0.0, jitter))
            delay = min(2.0, (2**attempt) * 0.5 * jitter)
            if deadline is not None:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise _DeadlineExceeded
                delay = min(delay, remaining)
            self._sleep(delay)
        assert response is not None
        if offer_race and response.status_code in (400, 404, 409):
            raise VastOfferUnavailable(
                f"Vast.ai offer is no longer rentable (status {response.status_code})"
            )
        if allow_not_found and response.status_code == 404:
            return response
        if response.status_code < 200 or response.status_code >= 300:
            raise VastError(f"Vast.ai request failed (status {response.status_code})")
        return response

    def _request_json(
        self,
        method: str,
        url: str,
        body: object | None,
        *,
        offer_race: bool = False,
        retry_429: bool = True,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        deadline: float | None = None,
    ) -> object:
        response = self._request(
            method,
            url,
            body,
            offer_race=offer_race,
            retry_429=retry_429,
            timeout_seconds=timeout_seconds,
            deadline=deadline,
        )
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VastError(
                f"Vast.ai response is invalid ({type(error).__name__})"
            ) from None
