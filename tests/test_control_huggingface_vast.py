from __future__ import annotations

from dataclasses import dataclass, FrozenInstanceError
from decimal import Decimal
import json
from urllib.parse import urlencode, urlsplit

import pytest

from defend_control.huggingface import HuggingFaceClient
from defend_control.huggingface import HuggingFaceError
from defend_control.model_registry import ADAPTER_REPO
from defend_control.types import LaunchSpec, ResourceProfile, VastInstance, VastOffer
from defend_control.vast import (
    VastClient,
    VastError,
    VastOfferUnavailable,
    VastSchedulingTimeout,
)


ADAPTER_SHA = "a" * 40
BASE_SHA = "b" * 64

# New policy defaults
_HIGH_VRAM = 141000  # representative of H200-class
_PROFILE = ResourceProfile()


@dataclass(frozen=True, repr=False)
class FakeRequest:
    method: str
    url: str
    headers: dict[str, str]
    json: object | None
    timeout: float

    def __repr__(self) -> str:
        return (
            f"FakeRequest(method={self.method!r}, url={self.url!r}, "
            f"header_names={tuple(self.headers)!r}, json={self.json!r}, "
            f"timeout={self.timeout!r})"
        )

    @property
    def path(self) -> str:
        return urlsplit(self.url).path


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class FakeHttp:
    def __init__(self) -> None:
        self._responses: list[tuple[str, str, FakeResponse]] = []
        self.requests: list[FakeRequest] = []

    def add_response(
        self,
        *,
        url: str,
        json: object,
        method: str = "GET",
        status_code: int = 200,
    ) -> None:
        self._responses.append(
            (
                method,
                url,
                FakeResponse(
                    status_code,
                    globals()["json"].dumps(json).encode("utf-8"),
                ),
            )
        )

    def add_raw_response(
        self,
        *,
        url: str,
        body: bytes,
        method: str = "GET",
        status_code: int = 200,
    ) -> None:
        self._responses.append((method, url, FakeResponse(status_code, body)))

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> FakeResponse:
        request = FakeRequest(method, url, dict(headers), json, timeout)
        self.requests.append(request)
        assert max_response_bytes in (64 * 1024, 4 * 1024 * 1024)
        for index, (expected_method, expected_url, response) in enumerate(
            self._responses
        ):
            if expected_method == method and expected_url == url:
                self._responses.pop(index)
                return response
        raise AssertionError(f"No fake response registered for {request!r}")

    @property
    def last_request(self) -> FakeRequest:
        return self.requests[-1]


class MutableClock:
    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self.current = values[-1]

    def __call__(self) -> float:
        if self._values:
            self.current = self._values.pop(0)
        return self.current


class DeadlineTransport:
    def __init__(
        self,
        clock: MutableClock,
        *,
        response: FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.clock = clock
        self.response = response
        self.error = error
        self.requests: list[FakeRequest] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> FakeResponse:
        self.requests.append(FakeRequest(method, url, dict(headers), json, timeout))
        assert max_response_bytes in (64 * 1024, 4 * 1024 * 1024)
        self.clock.current = 300.25
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.fixture
def fake_http() -> FakeHttp:
    return FakeHttp()


def test_huggingface_resolve_adapter_pins_both_revisions(fake_http: FakeHttp):
    fake_http.add_response(
        url=(
            "https://huggingface.co/api/models/"
            f"{ADAPTER_REPO}/revision/main"
        ),
        json={"sha": ADAPTER_SHA},
    )
    fake_http.add_response(
        url=(
            f"https://huggingface.co/{ADAPTER_REPO}/resolve/"
            f"{ADAPTER_SHA}/adapter_config.json"
        ),
        json={
            "peft_type": "LORA",
            "r": 64,
            "base_model_name_or_path": "Qwen/example-32B",
            "revision": BASE_SHA,
        },
    )

    spec = HuggingFaceClient(transport=fake_http).resolve_adapter(
        ADAPTER_REPO, "hf_synthetic_secret"
    )

    assert spec.adapter_repo == ADAPTER_REPO
    assert spec.adapter_revision == ADAPTER_SHA
    assert spec.base_repo == "Qwen/example-32B"
    assert spec.base_revision == BASE_SHA
    assert spec.peft_type == "LORA"
    assert spec.lora_rank == 64
    assert all(request.timeout == 30.0 for request in fake_http.requests)


def test_huggingface_token_is_sent_only_as_a_bearer_header(fake_http: FakeHttp):
    fake_http.add_response(
        url=(
            "https://huggingface.co/api/models/"
            f"{ADAPTER_REPO}/revision/main"
        ),
        json={"sha": ADAPTER_SHA},
    )
    fake_http.add_response(
        url=(
            f"https://huggingface.co/{ADAPTER_REPO}/resolve/"
            f"{ADAPTER_SHA}/adapter_config.json"
        ),
        json={
            "peft_type": "LORA",
            "r": 64,
            "base_model_name_or_path": "Qwen/example-32B",
            "revision": BASE_SHA,
        },
    )
    token = "hf_synthetic_secret"

    HuggingFaceClient(transport=fake_http).resolve_adapter(ADAPTER_REPO, token)

    for request in fake_http.requests:
        assert request.headers == {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        assert token not in request.url
        assert token not in json.dumps(request.json)
        assert token not in repr(request)


def test_vast_offer_search_uses_resource_profile_floor_and_families(
    fake_http: FakeHttp,
):
    """New policy: 140GB+ floor + A100/H100/H200/B200 families."""
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={
            "offers": [
                {
                    "id": 202,
                    "gpu_name": "H200 SXM",
                    "gpu_ram": _HIGH_VRAM,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 2.4,
                    "reliability": 0.99,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                },
                {
                    "id": 101,
                    "gpu_name": "A100 SXM4",
                    "gpu_ram": 81920,  # below new floor → rejected
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 1.75,
                    "reliability": 0.98,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                },
                {
                    "id": 303,
                    "gpu_name": "B200",
                    "gpu_ram": 180000,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 3.1,
                    "reliability": 0.99,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                },
            ]
        },
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    offers = client.search_offers(Decimal("3.50"), profile=_PROFILE)

    request = fake_http.last_request
    assert request.method == "POST"
    assert request.path == "/api/v0/bundles/"
    assert request.json["gpu_ram"] == {"gte": 140000}
    assert request.json["num_gpus"] == {"eq": 1}
    assert [offer.offer_id for offer in offers] == [202, 303]
    assert client.offer_search_summary == "provider returned 3; eligible 2"


def test_vast_accepts_h200_and_b200_names(fake_http: FakeHttp):
    for gpu_name in ("H200 SXM", "B200", "H100_NVL", "A100_SXM4"):
        fake_http.add_response(
            method="POST",
            url="https://console.vast.ai/api/v0/bundles/",
            json={
                "offers": [
                    {
                        "id": 4815,
                        "gpu_name": gpu_name,
                        "gpu_ram": _HIGH_VRAM,
                        "disk_space": 500,
                        "num_gpus": 1,
                        "dph_total": 2.1,
                        "reliability": 0.99,
                        "verified": True,
                        "rentable": True,
                        "rented": False,
                        "type": "on-demand",
                    }
                ]
            },
        )
        offers = VastClient("vast_synthetic_secret", transport=fake_http).search_offers(
            Decimal("3.00"), profile=_PROFILE
        )
        assert len(offers) == 1
        assert offers[0].gpu_name == gpu_name


def test_vast_create_has_no_hf_or_vllm_secret(fake_http: FakeHttp):
    offer = VastOffer(
        101,
        "H200 SXM",
        _HIGH_VRAM,
        Decimal("2.10"),
        Decimal("0.99"),
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/101/",
        json={"success": True, "new_contract": 4815},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    instance = client.create_instance(offer, LaunchSpec.default())

    body = fake_http.last_request.json
    serialized = json.dumps(body)
    assert "HF_TOKEN" not in serialized
    assert "API_KEY" not in serialized
    assert instance.instance_id == 4815
    assert instance.gpu_name == offer.gpu_name


def test_vast_create_accepts_defendcoder_launch_and_rejects_other_launches(
    fake_http: FakeHttp,
):
    offer = VastOffer(
        202,
        "A100 SXM4",
        81920,
        Decimal("2.60"),
        Decimal("0.99"),
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/202/",
        json={"success": True, "new_contract": 6001},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    coder_launch = LaunchSpec(
        "vllm/vllm-openai:v0.15.0",
        160,
        "ssh_proxy",
        "defendcoder-vllm",
    )
    instance = client.create_instance(offer, coder_launch)

    body = fake_http.last_request.json
    assert body["label"] == "defendcoder-vllm"
    assert body["image"] == "vllm/vllm-openai:v0.15.0"
    assert body["runtype"] == "ssh_proxy"
    assert instance.instance_id == 6001

    rogue = LaunchSpec(
        "example/unknown-image:latest",
        999,
        "args",
        "defendcoder-vllm",
    )
    with pytest.raises(ValueError, match="approved DEFEND or DEFENDcoder"):
        client.create_instance(offer, rogue)
    legacy = LaunchSpec(
        "vllm/vllm-openai:v0.10.0",
        160,
        "ssh_proxy",
        "defend-vllm",
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/202/",
        json={"success": True, "new_contract": 6002},
    )
    assert client.create_instance(offer, legacy).instance_id == 6002


def test_vast_create_rejects_undocumented_ssh_direc_token(fake_http: FakeHttp):
    offer = VastOffer(
        205,
        "A100 SXM4",
        81920,
        Decimal("2.60"),
        Decimal("0.9991"),
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)
    for runtype in ("ssh_direc", "ssh_direc ssh_proxy", "ssh_proxy ssh_direc"):
        launch = LaunchSpec(
            "vllm/vllm-openai:v0.15.0",
            160,
            runtype,
            "defendcoder-vllm",
        )
        with pytest.raises(ValueError, match="ssh_direc is rejected"):
            client.create_instance(offer, launch)
    assert fake_http.requests == []


def test_task5_types_are_immutable_and_launch_default_is_exact():
    launch = LaunchSpec.default()
    assert launch == LaunchSpec(
        "vllm/vllm-openai:v0.10.0",
        160,
        "ssh_proxy",
        "defend-vllm",
    )
    with pytest.raises(FrozenInstanceError):
        launch.disk_gb = 1  # type: ignore[misc]

    profile = ResourceProfile()
    assert profile.min_gpu_ram_mb == 140_000
    assert "H200" in profile.allowed_gpu_families
    assert "B200" in profile.allowed_gpu_families


def test_vast_heavy_create_requests_documented_direct_ssh(fake_http: FakeHttp):
    offer = VastOffer(
        303,
        "A100 SXM4",
        81920,
        Decimal("2.70"),
        Decimal("0.9995"),
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/303/",
        json={"success": True, "new_contract": 7001},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    heavy = LaunchSpec.coder_heavy_direct()
    instance = client.create_instance(offer, heavy)

    body = fake_http.last_request.json
    assert body["runtype"] == "ssh_direct"
    assert body["label"] == "defendcoder-vllm"
    assert body["image"] == heavy.image
    assert body["disk"] == 160
    assert body["onstart"] is None
    assert body["env"] == {}
    assert instance.instance_id == 7001
    assert len(fake_http.requests) == 1


def test_vast_build_create_payload_returns_exact_serialized_request(fake_http: FakeHttp):
    offer = VastOffer(305, "A100 SXM4", 81920, Decimal("2.60"), Decimal("0.999"))
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    payload = client.build_create_payload(offer, LaunchSpec.coder_heavy_direct())

    assert payload["runtype"] == "ssh_direct"
    assert payload["client_id"] == "me"
    assert payload["target_state"] == "running"
    assert payload["cancel_unavail"] is True
    assert payload["template_hash_id"] is None
    assert payload["image"] == "vllm/vllm-openai:v0.10.0"
    assert fake_http.requests == []
    with pytest.raises(ValueError, match="ssh_direc is rejected"):
        client.build_create_payload(
            offer,
            LaunchSpec(
                "vllm/vllm-openai:v0.15.0",
                160,
                "ssh_direc ssh_proxy",
                "defendcoder-vllm",
            ),
        )
    assert fake_http.requests == []


def test_create_instance_sends_exactly_build_create_payload(fake_http: FakeHttp):
    offer = VastOffer(306, "A100 SXM4", 81920, Decimal("2.60"), Decimal("0.999"))
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/306/",
        json={"success": True, "new_contract": 7003},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    heavy = LaunchSpec.coder_heavy_direct()
    expected = client.build_create_payload(offer, heavy)

    client.create_instance(offer, heavy)

    assert fake_http.last_request.json == expected
    assert expected["runtype"] == "ssh_direct"


def test_vast_default_defend_lane_payload_is_unchanged(fake_http: FakeHttp):
    offer = VastOffer(304, "H100 SXM", 81920, Decimal("2.50"), Decimal("0.99"))
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/304/",
        json={"success": True, "new_contract": 7002},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    client.create_instance(offer, LaunchSpec.default())

    body = fake_http.last_request.json
    assert body["runtype"] == "ssh_proxy"
    assert body["label"] == "defend-vllm"
    assert body["image"] == "vllm/vllm-openai:v0.10.0"


def test_vast_parse_instance_captures_provider_image_runtype():
    raw = {
        "id": 7005,
        "actual_status": "running",
        "ssh_host": "ssh5.vast.ai",
        "ssh_port": 37462,
        "gpu_name": "A100 SXM4",
        "gpu_ram": 81920,
        "dph_total": "2.617777777777777",
        "machine_id": 5908,
        "image_runtype": "ssh_direct",
    }
    instance = VastClient._parse_instance(raw, 7005)
    assert instance.image_runtype == "ssh_direct"
    assert instance.machine_id == 5908
    assert instance.ssh_host == "ssh5.vast.ai"
