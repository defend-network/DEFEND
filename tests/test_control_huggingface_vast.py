from __future__ import annotations

from dataclasses import dataclass, FrozenInstanceError
from decimal import Decimal
import json
from urllib.parse import urlencode, urlsplit

import pytest

from defend_control.huggingface import HuggingFaceClient
from defend_control.huggingface import HuggingFaceError
from defend_control.types import LaunchSpec, VastInstance, VastOffer
from defend_control.vast import (
    VastClient,
    VastError,
    VastOfferUnavailable,
    VastSchedulingTimeout,
)


ADAPTER_SHA = "a" * 40
BASE_SHA = "b" * 64
ADAPTER_REPO = "Defend-network/defend-qwen-32b-lora"


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
        assert max_response_bytes == 64 * 1024
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
        assert max_response_bytes == 64 * 1024
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


def test_huggingface_resolves_missing_base_revision_and_rejects_gguf(
    fake_http: FakeHttp,
):
    metadata_url = (
        "https://huggingface.co/api/models/"
        f"{ADAPTER_REPO}/revision/main"
    )
    config_url = (
        f"https://huggingface.co/{ADAPTER_REPO}/resolve/"
        f"{ADAPTER_SHA}/adapter_config.json"
    )
    fake_http.add_response(url=metadata_url, json={"sha": ADAPTER_SHA})
    fake_http.add_response(
        url=config_url,
        json={
            "peft_type": "LORA",
            "r": 64,
            "base_model_name_or_path": "Qwen/example-32B",
        },
    )
    fake_http.add_response(
        url=(
            "https://huggingface.co/api/models/"
            "Qwen/example-32B/revision/main"
        ),
        json={"sha": BASE_SHA},
    )

    spec = HuggingFaceClient(transport=fake_http).resolve_adapter(
        ADAPTER_REPO, "hf_synthetic_secret"
    )

    assert spec.base_revision == BASE_SHA

    fake_http.add_response(url=metadata_url, json={"sha": ADAPTER_SHA})
    fake_http.add_response(
        url=config_url,
        json={
            "peft_type": "LORA",
            "r": 64,
            "base_model_name_or_path": "Defend-network/defend-qwen-32b-gguf",
            "revision": BASE_SHA,
        },
    )
    with pytest.raises(HuggingFaceError, match="base repository"):
        HuggingFaceClient(transport=fake_http).resolve_adapter(
            ADAPTER_REPO, "hf_synthetic_secret"
        )


@pytest.mark.parametrize(
    ("metadata", "config", "match"),
    [
        ({"sha": "main"}, {}, "adapter revision"),
        (
            {"sha": ADAPTER_SHA},
            {
                "peft_type": "IA3",
                "r": 64,
                "base_model_name_or_path": "Qwen/example-32B",
                "revision": BASE_SHA,
            },
            "LORA",
        ),
        (
            {"sha": ADAPTER_SHA},
            {
                "peft_type": "LORA",
                "r": 64,
                "base_model_name_or_path": "local-path",
                "revision": BASE_SHA,
            },
            "base repository",
        ),
        (
            {"sha": ADAPTER_SHA},
            {
                "peft_type": "LORA",
                "r": 64,
                "base_model_name_or_path": "Qwen/example-32B",
                "revision": "main",
            },
            "base revision",
        ),
    ],
)
def test_huggingface_requires_lora_repositories_and_immutable_revisions(
    fake_http: FakeHttp,
    metadata: object,
    config: object,
    match: str,
):
    fake_http.add_response(
        url=(
            "https://huggingface.co/api/models/"
            f"{ADAPTER_REPO}/revision/main"
        ),
        json=metadata,
    )
    if metadata == {"sha": ADAPTER_SHA}:
        fake_http.add_response(
            url=(
                f"https://huggingface.co/{ADAPTER_REPO}/resolve/"
                f"{ADAPTER_SHA}/adapter_config.json"
            ),
            json=config,
        )

    with pytest.raises(HuggingFaceError, match=match):
        HuggingFaceClient(transport=fake_http).resolve_adapter(
            ADAPTER_REPO, "hf_synthetic_secret"
        )


@pytest.mark.parametrize("rank", [None, True, 0, -1, 513, "64"])
def test_huggingface_requires_a_bounded_integer_lora_rank(
    fake_http: FakeHttp,
    rank: object,
):
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
            "r": rank,
            "base_model_name_or_path": "Qwen/example-32B",
            "revision": BASE_SHA,
        },
    )

    with pytest.raises(HuggingFaceError, match="LoRA rank"):
        HuggingFaceClient(transport=fake_http).resolve_adapter(
            ADAPTER_REPO, "hf_synthetic_secret"
        )


def test_huggingface_failure_exposes_only_status_or_error_type(
    fake_http: FakeHttp,
):
    token = "hf_synthetic_secret"
    fake_http.add_response(
        url=(
            "https://huggingface.co/api/models/"
            f"{ADAPTER_REPO}/revision/main"
        ),
        status_code=401,
        json={"error": f"private provider detail {token}"},
    )

    with pytest.raises(HuggingFaceError) as pending:
        HuggingFaceClient(transport=fake_http).resolve_adapter(ADAPTER_REPO, token)

    assert str(pending.value) == "Hugging Face request failed (status 401)"
    assert token not in repr(pending.value)


def test_vast_offer_search_is_verified_on_demand_single_80gb_and_capped(
    fake_http: FakeHttp,
):
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={
            "offers": [
                {
                    "id": 202,
                    "gpu_name": "H100 SXM",
                    "gpu_ram": 81920,
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
                    "gpu_ram": 81920,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 1.75,
                    "storage_cost": 0.15,
                    "storage_total_cost": 0.032,
                    "reliability": 0.98,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                },
                {
                    "id": 303,
                    "gpu_name": "A100",
                    "gpu_ram": 40960,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 1.0,
                    "reliability": 0.97,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                },
            ]
        },
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    offers = client.search_offers(Decimal("2.50"))

    request = fake_http.last_request
    assert request.method == "POST"
    assert request.path == "/api/v0/bundles/"
    assert request.json["type"] == "on-demand"
    assert request.json["verified"] == {"eq": True}
    assert request.json["rentable"] == {"eq": True}
    assert request.json["rented"] == {"eq": False}
    assert request.json["num_gpus"] == {"eq": 1}
    assert request.json["gpu_ram"] == {"gte": 80000}
    assert request.json["disk_space"] == {"gte": 160}
    assert request.json["direct_port_count"] == {"gte": 1}
    assert request.json["reliability"] == {"gte": 0.98}
    assert request.json["dph_total"] == {"lte": 2.5}
    assert request.json["allocated_storage"] == 160
    assert request.json["limit"] == 20
    assert [offer.offer_id for offer in offers] == [101, 202]
    assert client.offer_search_summary == "provider returned 3; eligible 2"
    assert offers[0].storage_cost_per_gb_month == Decimal("0.15")
    assert offers[0].storage_total_hourly == Decimal("0.032")


def test_vast_lists_exact_labeled_instances_for_safe_recovery(
    fake_http: FakeHttp,
):
    filters = json.dumps(
        {"label": {"eq": "defend-vllm"}}, separators=(",", ":")
    )
    url = (
        "https://console.vast.ai/api/v1/instances/?"
        + urlencode({"limit": 25, "select_filters": filters})
    )
    fake_http.add_response(
        url=url,
        json={
            "success": True,
            "instances_found": 2,
            "total_instances": 2,
            "next_token": None,
            "instances": [
                {
                    "id": 47468263,
                    "label": "defend-vllm",
                    "actual_status": "running",
                },
                {
                    "id": 47468264,
                    "label": "other-workload",
                    "actual_status": "running",
                },
            ],
        },
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    assert client.list_labeled_instance_ids("defend-vllm") == (47468263,)

    request = fake_http.last_request
    assert request.method == "GET"
    assert request.url == url
    assert request.json is None
    assert "vast_synthetic_secret" not in request.url


def test_vast_rejects_instance_list_that_claims_hidden_candidates(
    fake_http: FakeHttp,
):
    filters = json.dumps(
        {"label": {"eq": "defend-vllm"}}, separators=(",", ":")
    )
    url = (
        "https://console.vast.ai/api/v1/instances/?"
        + urlencode({"limit": 25, "select_filters": filters})
    )
    fake_http.add_response(
        url=url,
        json={
            "success": True,
            "instances_found": 1,
            "total_instances": 26,
            "next_token": None,
            "instances": [
                {
                    "id": 47468263,
                    "label": "defend-vllm",
                    "actual_status": "running",
                }
            ],
        },
    )

    with pytest.raises(VastError, match="instance list response is invalid"):
        VastClient(
            "vast_synthetic_secret", transport=fake_http
        ).list_labeled_instance_ids("defend-vllm")


@pytest.mark.parametrize("gpu_name", ["A100_SXM4", "H100_NVL"])
def test_vast_accepts_official_underscore_gpu_names(
    fake_http: FakeHttp, gpu_name: str
):
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={
            "offers": [
                {
                    "id": 4815,
                    "gpu_name": gpu_name,
                    "gpu_ram": 81920,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 1.75,
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
        Decimal("3.00")
    )

    assert len(offers) == 1
    assert offers[0].gpu_name == gpu_name


def test_vast_accepts_documented_verification_and_is_bid_offer_fields(
    fake_http: FakeHttp,
):
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={
            "offers": [
                {
                    "id": 4815,
                    "gpu_name": "A100_SXM4",
                    "gpu_ram": 81920,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 1.75,
                    "reliability": 0.99,
                    "verification": "verified",
                    "rentable": True,
                    "rented": False,
                    "is_bid": False,
                }
            ]
        },
    )

    offers = VastClient("vast_synthetic_secret", transport=fake_http).search_offers(
        Decimal("3.00")
    )

    assert len(offers) == 1
    assert offers[0].offer_id == 4815


def test_vast_offer_search_locally_revalidates_every_constraint(
    fake_http: FakeHttp,
):
    valid = {
        "id": 1,
        "gpu_name": "H100 SXM",
        "gpu_ram": 81920,
        "disk_space": 500,
        "num_gpus": 1,
        "dph_total": 2.0,
        "reliability": 0.99,
        "verified": True,
        "rentable": True,
        "rented": False,
        "type": "on-demand",
    }
    invalid_changes = (
        {"verified": False},
        {"rentable": False},
        {"rented": True},
        {"type": "interruptible"},
        {"num_gpus": 2},
        {"num_gpus": True},
        {"gpu_ram": 79999},
        {"disk_space": 159},
        {"gpu_name": "MI300X"},
        {"dph_total": 2.51},
        {"reliability": 0.979},
        {"reliability": 1.01},
    )
    offers = [valid]
    for offer_id, change in enumerate(invalid_changes, start=2):
        offers.append({**valid, "id": offer_id, **change})
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={"offers": offers},
    )

    selected = VastClient(
        "vast_synthetic_secret", transport=fake_http
    ).search_offers(Decimal("2.50"))

    assert [offer.offer_id for offer in selected] == [1]


def test_vast_create_has_no_hf_or_vllm_secret(fake_http: FakeHttp):
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.98"),
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
    assert body == {
        "client_id": "me",
        "image": "vllm/vllm-openai:v0.10.0",
        "env": {},
        "disk": 160,
        "runtype": "ssh_direc ssh_proxy",
        "target_state": "running",
        "cancel_unavail": True,
        "label": "defend-vllm",
        "onstart": None,
        "image_login": None,
        "python_utf8": False,
        "lang_utf8": False,
        "use_jupyter_lab": False,
        "jupyter_dir": None,
        "force": False,
        "template_hash_id": None,
        "user": None,
    }
    assert instance.instance_id == 4815
    assert instance.gpu_name == offer.gpu_name


def test_vast_create_rejects_provider_declared_failure_without_body_leak(
    fake_http: FakeHttp,
):
    token = "vast_synthetic_secret"
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.98"),
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/101/",
        json={
            "success": False,
            "new_contract": 4815,
            "msg": f"private provider failure {token}",
        },
    )

    with pytest.raises(VastOfferUnavailable) as pending:
        VastClient(token, transport=fake_http).create_instance(
            offer, LaunchSpec.default()
        )

    assert str(pending.value) == "Vast.ai offer is no longer rentable"
    assert token not in repr(pending.value)


def test_vast_lifecycle_uses_only_official_methods_paths_and_state_body(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    fake_http.add_response(
        url=instance_url,
        json={
            "instances": {
                "id": 4815,
                "actual_status": "running",
                "ssh_host": "ssh.example.test",
                "ssh_port": 2222,
                "gpu_name": "A100 SXM4",
                "gpu_ram": 81920,
                "dph_total": 1.75,
            }
        },
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/instances/4815/",
        json={"success": True},
    )
    fake_http.add_raw_response(
        method="DELETE", url=instance_url, status_code=204, body=b""
    )
    fake_http.add_raw_response(url=instance_url, status_code=404, body=b"")
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    instance = client.show_instance(4815)
    client.set_state(4815, "stopped")
    destroyed = client.destroy_instance(4815, confirmed_instance_id=4815)

    assert instance.actual_status == "running"
    assert [(request.method, request.path, request.json) for request in fake_http.requests] == [
        ("GET", "/api/v0/instances/4815/", None),
        ("PUT", "/api/v0/instances/4815/", {"state": "stopped"}),
        ("DELETE", "/api/v0/instances/4815/", None),
        ("GET", "/api/v0/instances/4815/", None),
    ]
    assert destroyed is True


def test_vast_ssh_key_is_posted_only_when_exact_key_is_absent(fake_http: FakeHttp):
    ssh_url = "https://console.vast.ai/api/v0/ssh/"
    public_key = "ssh-ed25519 AAAAC3NzaSynthetic defend-control"
    fake_http.add_response(
        url=ssh_url,
        json={"ssh_keys": [{"id": 12, "ssh_key": public_key}]},
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    assert client.ensure_account_ssh_key(public_key) == 12
    assert len(fake_http.requests) == 1

    fake_http.add_response(url=ssh_url, json={"ssh_keys": []})
    fake_http.add_response(
        method="POST", url=ssh_url, json={"id": 13, "success": True}
    )

    assert client.ensure_account_ssh_key(public_key) == 13
    assert fake_http.last_request.json == {"ssh_key": public_key}


def test_vast_waits_through_null_and_loading_until_running(fake_http: FakeHttp):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    for status in (None, "loading", "running"):
        fake_http.add_response(
            url=instance_url,
            json={
                "id": 4815,
                "actual_status": status,
                "ssh_host": "ssh.example.test" if status == "running" else None,
                "ssh_port": 2222 if status == "running" else None,
                "gpu_name": "A100 SXM4",
                "gpu_ram": 81920,
                "dph_total": 1.75,
            },
        )
    sleeps = []
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        sleep=sleeps.append,
        monotonic=iter(tuple(float(value) for value in range(13))).__next__,
    )

    instance = client.wait_until_running(4815, poll_interval_seconds=0.25)

    assert instance.actual_status == "running"
    assert sleeps == [0.25, 0.25]


def test_vast_wait_accepts_documented_partial_loading_response(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    fake_http.add_response(
        url=instance_url,
        json={
            "instances": {
                "actual_status": "loading",
                "ssh_host": "ssh.example.test",
                "ssh_port": 2222,
            }
        },
    )
    fake_http.add_response(
        url=instance_url,
        json={"instances": _running_instance_document()},
    )
    sleeps: list[float] = []
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
    )

    instance = client.wait_until_running(4815)

    assert instance.actual_status == "running"
    assert sleeps == [10.0]


@pytest.mark.parametrize("status", ["exited", "unknown", "offline"])
def test_vast_terminal_provisioning_states_fail_safely(
    fake_http: FakeHttp, status: str
):
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/",
        json={
            "id": 4815,
            "actual_status": status,
            "ssh_host": None,
            "ssh_port": None,
            "gpu_name": "A100 SXM4",
            "gpu_ram": 81920,
            "dph_total": 1.75,
        },
    )
    client = VastClient(
        "vast_synthetic_secret", transport=fake_http, monotonic=lambda: 0.0
    )

    with pytest.raises(VastError, match=f"terminal status {status}"):
        client.wait_until_running(4815)


def test_vast_restart_wait_tolerates_stale_exited_before_running(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    fake_http.add_response(
        url=instance_url,
        json={**_running_instance_document(), "actual_status": "exited"},
    )
    fake_http.add_response(url=instance_url, json=_running_instance_document())
    sleeps: list[float] = []
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
    )

    instance = client.wait_until_running(
        4815, allow_stopped_transition=True
    )

    assert instance.actual_status == "running"
    assert sleeps == [10.0]


def test_vast_restart_scheduling_clears_before_thirty_seconds(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    for status in ("scheduling", "scheduling", "running"):
        fake_http.add_response(
            url=instance_url,
            json={**_running_instance_document(), "actual_status": status},
        )

    class AdvancingClock:
        current = 0.0

        def __call__(self):
            return self.current

        def sleep(self, seconds):
            self.current += seconds

    clock = AdvancingClock()
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=clock,
        sleep=clock.sleep,
    )

    instance = client.wait_until_running(
        4815,
        allow_stopped_transition=True,
        scheduling_timeout_seconds=30.0,
    )

    assert instance.actual_status == "running"
    assert clock.current == 20.0


def test_vast_restart_scheduling_stops_at_thirty_seconds(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    for _ in range(4):
        fake_http.add_response(
            url=instance_url,
            json={
                **_running_instance_document(),
                "actual_status": "scheduling",
            },
        )

    class AdvancingClock:
        current = 0.0

        def __call__(self):
            return self.current

        def sleep(self, seconds):
            self.current += seconds

    clock = AdvancingClock()
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(VastSchedulingTimeout) as pending:
        client.wait_until_running(
            4815,
            allow_stopped_transition=True,
            scheduling_timeout_seconds=30.0,
        )

    assert pending.value.instance_id == 4815
    assert str(pending.value) == (
        "Vast.ai restart remained scheduled for 30 seconds"
    )
    assert clock.current == 30.0


@pytest.mark.parametrize("offer_type", ["bid", "reserved"])
def test_vast_offer_response_rejects_every_non_on_demand_type(
    fake_http: FakeHttp,
    offer_type: str,
):
    fake_http.add_response(
        method="POST",
        url="https://console.vast.ai/api/v0/bundles/",
        json={
            "offers": [
                {
                    "id": 909,
                    "gpu_name": "A100 SXM4",
                    "gpu_ram": 81920,
                    "disk_space": 500,
                    "num_gpus": 1,
                    "dph_total": 0.75,
                    "reliability": 0.999,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": offer_type,
                }
            ]
        },
    )

    assert VastClient(
        "vast_synthetic_secret", transport=fake_http
    ).search_offers(Decimal("2.50")) == ()


def test_vast_unrecognized_terminal_status_is_not_reflected(fake_http: FakeHttp):
    sentinel = "provider_status_private_sentinel"
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/",
        json={
            "id": 4815,
            "actual_status": sentinel,
            "ssh_host": None,
            "ssh_port": None,
            "gpu_name": "A100 SXM4",
            "gpu_ram": 81920,
            "dph_total": 1.75,
        },
    )
    client = VastClient(
        "vast_synthetic_secret", transport=fake_http, monotonic=lambda: 0.0
    )

    with pytest.raises(VastError) as pending:
        client.wait_until_running(4815)

    assert str(pending.value) == (
        "Vast.ai provisioning failed (terminal status unrecognized)"
    )
    assert sentinel not in repr(pending.value)


def test_vast_provisioning_timeout_is_five_minutes(fake_http: FakeHttp):
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/",
        json={
            "id": 4815,
            "actual_status": "loading",
            "ssh_host": None,
            "ssh_port": None,
            "gpu_name": "A100 SXM4",
            "gpu_ram": 81920,
            "dph_total": 1.75,
        },
    )
    clock = iter((0.0, 300.0)).__next__
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        sleep=lambda _seconds: None,
        monotonic=clock,
    )

    with pytest.raises(VastError, match="timed out after 300 seconds"):
        client.wait_until_running(4815)


def _running_instance_document() -> dict[str, object]:
    return {
        "id": 4815,
        "actual_status": "running",
        "ssh_host": "ssh.example.test",
        "ssh_port": 2222,
        "gpu_name": "A100 SXM4",
        "gpu_ram": 81920,
        "dph_total": 1.75,
    }


def test_vast_running_just_before_deadline_uses_only_remaining_request_budget(
    fake_http: FakeHttp,
):
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/",
        json=_running_instance_document(),
    )
    clock = iter((0.0, 299.0, 299.0, 299.5, 299.999)).__next__
    client = VastClient(
        "vast_synthetic_secret", transport=fake_http, monotonic=clock
    )

    assert client.wait_until_running(4815).actual_status == "running"
    assert fake_http.last_request.timeout == pytest.approx(1.0)


def test_vast_running_at_deadline_times_out(fake_http: FakeHttp):
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/",
        json=_running_instance_document(),
    )
    clock = iter((0.0, 299.0, 300.0)).__next__
    client = VastClient(
        "vast_synthetic_secret", transport=fake_http, monotonic=clock
    )

    with pytest.raises(VastError, match="timed out after 300 seconds"):
        client.wait_until_running(4815)


def test_vast_after_deadline_makes_no_status_request(fake_http: FakeHttp):
    clock = iter((0.0, 300.001)).__next__
    client = VastClient(
        "vast_synthetic_secret", transport=fake_http, monotonic=clock
    )

    with pytest.raises(VastError, match="timed out after 300 seconds"):
        client.wait_until_running(4815)

    assert fake_http.requests == []


def test_vast_clamps_sleep_and_next_request_to_deadline(fake_http: FakeHttp):
    loading = {**_running_instance_document(), "actual_status": "loading"}
    fake_http.add_response(
        url="https://console.vast.ai/api/v0/instances/4815/", json=loading
    )
    sleeps = []
    clock = iter((0.0, 299.75, 299.75, 299.8, 299.8, 300.0)).__next__
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=clock,
        sleep=sleeps.append,
    )

    with pytest.raises(VastError, match="timed out after 300 seconds"):
        client.wait_until_running(4815, poll_interval_seconds=2.0)

    assert len(fake_http.requests) == 1
    assert fake_http.last_request.timeout == pytest.approx(0.25)
    assert sleeps == [pytest.approx(0.2)]


def test_vast_retry_reaching_deadline_issues_no_second_status_request(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    fake_http.add_response(
        url=instance_url, status_code=429, json={"error": "limited"}
    )
    fake_http.add_response(url=instance_url, json=_running_instance_document())
    sleeps = []
    clock = iter((0.0, 299.75, 299.75, 300.25)).__next__
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=clock,
        sleep=sleeps.append,
        jitter=lambda: 1.0,
    )

    with pytest.raises(VastError) as pending:
        client.wait_until_running(4815)

    assert str(pending.value) == "Vast.ai provisioning timed out after 300 seconds"
    assert len(fake_http.requests) == 1
    assert fake_http.last_request.timeout == pytest.approx(0.25)
    assert sleeps == []


def test_vast_retry_refreshes_timeout_and_clamps_each_sleep_to_deadline(
    fake_http: FakeHttp,
):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    for _ in range(2):
        fake_http.add_response(
            url=instance_url, status_code=429, json={"error": "limited"}
        )
    fake_http.add_response(url=instance_url, json=_running_instance_document())
    sleeps = []
    clock = iter(
        (
            0.0,
            299.0,
            299.0,
            299.1,
            299.2,
            299.6,
            299.7,
            299.75,
            299.99,
            299.995,
            299.999,
        )
    ).__next__
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        monotonic=clock,
        sleep=sleeps.append,
        jitter=lambda: 1.0,
    )

    assert client.wait_until_running(4815).actual_status == "running"
    assert [request.timeout for request in fake_http.requests] == pytest.approx(
        [1.0, 0.4, 0.01]
    )
    assert sleeps == pytest.approx([0.5, 0.25])


@pytest.mark.parametrize("outcome", ["exception", "status", "malformed"])
def test_vast_overdue_transport_outcome_maps_to_fixed_provisioning_timeout(
    outcome: str,
):
    sentinel = "private_transport_deadline_sentinel"
    clock = MutableClock(0.0, 299.75, 299.75)
    if outcome == "exception":
        transport = DeadlineTransport(
            clock, error=TimeoutError(f"transport detail {sentinel}")
        )
    elif outcome == "status":
        transport = DeadlineTransport(
            clock,
            response=FakeResponse(
                500, json.dumps({"error": sentinel}).encode("utf-8")
            ),
        )
    else:
        transport = DeadlineTransport(
            clock, response=FakeResponse(200, f"{{{sentinel}".encode("utf-8"))
        )
    client = VastClient(
        "vast_synthetic_secret", transport=transport, monotonic=clock
    )

    with pytest.raises(VastError) as pending:
        client.wait_until_running(4815)

    assert str(pending.value) == "Vast.ai provisioning timed out after 300 seconds"
    assert sentinel not in repr(pending.value)
    assert len(transport.requests) == 1
    assert transport.requests[0].timeout == pytest.approx(0.25)


def test_vast_offer_rented_race_and_failure_never_expose_provider_body(
    fake_http: FakeHttp,
):
    token = "vast_synthetic_secret"
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.98"),
    )
    fake_http.add_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/asks/101/",
        status_code=409,
        json={"error": f"already rented private detail {token}"},
    )

    with pytest.raises(VastOfferUnavailable) as pending:
        VastClient(token, transport=fake_http).create_instance(
            offer, LaunchSpec.default()
        )

    assert str(pending.value) == (
        "Vast.ai offer is no longer rentable (status 409)"
    )
    assert token not in repr(pending.value)


def test_vast_stopped_instance_warns_that_disk_charges_may_continue():
    instance = VastInstance(
        4815,
        "stopped",
        None,
        None,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
    )

    assert "disk charges may continue" in VastClient.billing_warning(instance)


def test_vast_destroy_requires_exact_id_and_reports_success_or_safe_failure(
    fake_http: FakeHttp,
):
    token = "vast_synthetic_secret"
    client = VastClient(token, transport=fake_http)
    with pytest.raises(ValueError, match="exact instance ID"):
        client.destroy_instance(4815, confirmed_instance_id=4814)
    assert fake_http.requests == []

    fake_http.add_response(
        method="DELETE",
        url="https://console.vast.ai/api/v0/instances/4815/",
        status_code=500,
        json={"error": f"private destroy failure {token}"},
    )
    with pytest.raises(VastError) as pending:
        client.destroy_instance(4815, confirmed_instance_id=4815)

    assert str(pending.value) == "Vast.ai request failed (status 500)"
    assert token not in repr(pending.value)


def test_vast_destroy_waits_until_exact_instance_is_absent(fake_http: FakeHttp):
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"
    fake_http.add_response(
        method="DELETE", url=instance_url, json={"success": True}
    )
    fake_http.add_response(
        url=instance_url,
        json={
            "instances": {
                "id": 4815,
                "actual_status": "stopped",
                "ssh_host": None,
                "ssh_port": None,
                "gpu_name": "A100 SXM4",
                "gpu_ram": 81920,
                "dph_total": 1.75,
            }
        },
    )
    fake_http.add_raw_response(url=instance_url, status_code=404, body=b"")
    sleeps: list[float] = []

    assert VastClient(
        "vast_synthetic_secret", transport=fake_http, sleep=sleeps.append
    ).destroy_instance(4815, confirmed_instance_id=4815) is True

    assert [(request.method, request.path) for request in fake_http.requests] == [
        ("DELETE", "/api/v0/instances/4815/"),
        ("GET", "/api/v0/instances/4815/"),
        ("GET", "/api/v0/instances/4815/"),
    ]
    assert sleeps == [2.0]


def test_vast_destroy_verification_has_a_safe_thirty_second_deadline():
    instance_url = "https://console.vast.ai/api/v0/instances/4815/"

    class StillPresentTransport:
        def __init__(self) -> None:
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
            assert url == instance_url
            assert max_response_bytes == 64 * 1024
            if method == "DELETE":
                return FakeResponse(200, b'{"success":true}')
            assert method == "GET"
            return FakeResponse(
                200,
                b'{"instances":{"id":4815,"actual_status":"stopped"}}',
            )

    clock = MutableClock(0.0)
    transport = StillPresentTransport()

    def advance(seconds: float) -> None:
        clock.current += seconds

    client = VastClient(
        "vast_synthetic_secret",
        transport=transport,
        monotonic=clock,
        sleep=advance,
    )

    with pytest.raises(VastError) as pending:
        client.destroy_instance(4815, confirmed_instance_id=4815)

    assert str(pending.value) == (
        "Vast.ai destruction could not be verified after 30 seconds"
    )
    assert len(transport.requests) == 16
    assert transport.requests[-1].timeout == pytest.approx(2.0)


@pytest.mark.parametrize("document", [{"success": False}, {"success": "true"}])
@pytest.mark.parametrize(
    ("operation", "safe_error"),
    [
        ("state", "Vast.ai state change failed"),
        ("destroy", "Vast.ai destruction failed"),
        ("ssh_key", "Vast.ai SSH key creation failed"),
    ],
)
def test_vast_mutations_reject_2xx_false_or_malformed_success(
    fake_http: FakeHttp,
    operation: str,
    safe_error: str,
    document: object,
):
    token = "vast_mutation_sentinel"
    client = VastClient(token, transport=fake_http)
    if operation == "state":
        fake_http.add_response(
            method="PUT",
            url="https://console.vast.ai/api/v0/instances/4815/",
            json={**document, "detail": token},
        )
        invoke = lambda: client.set_state(4815, "stopped")
    elif operation == "destroy":
        fake_http.add_response(
            method="DELETE",
            url="https://console.vast.ai/api/v0/instances/4815/",
            json={**document, "detail": token},
        )
        invoke = lambda: client.destroy_instance(
            4815, confirmed_instance_id=4815
        )
    else:
        fake_http.add_response(
            url="https://console.vast.ai/api/v0/ssh/", json={"ssh_keys": []}
        )
        fake_http.add_response(
            method="POST",
            url="https://console.vast.ai/api/v0/ssh/",
            json={**document, "id": 12, "detail": token},
        )
        invoke = lambda: client.ensure_account_ssh_key(
            "ssh-ed25519 AAAAC3NzaMutation defend-control"
        )

    with pytest.raises(VastError) as pending:
        invoke()

    assert str(pending.value) == safe_error
    assert token not in repr(pending.value)


def test_vast_mutations_accept_documented_empty_success_and_reconcile_ssh_key(
    fake_http: FakeHttp,
):
    ssh_url = "https://console.vast.ai/api/v0/ssh/"
    public_key = "ssh-ed25519 AAAAC3NzaEmptySuccess defend-control"
    fake_http.add_raw_response(
        method="PUT",
        url="https://console.vast.ai/api/v0/instances/4815/",
        status_code=204,
        body=b"",
    )
    fake_http.add_response(url=ssh_url, json={"ssh_keys": []})
    fake_http.add_raw_response(
        method="POST", url=ssh_url, status_code=204, body=b""
    )
    fake_http.add_response(
        url=ssh_url, json={"ssh_keys": [{"id": 12, "ssh_key": public_key}]}
    )
    client = VastClient("vast_synthetic_secret", transport=fake_http)

    assert client.set_state(4815, "stopped") is True
    assert client.ensure_account_ssh_key(public_key) == 12


@pytest.mark.parametrize("status_code", [200, 201, 202])
@pytest.mark.parametrize(
    ("operation", "safe_error"),
    [
        ("state", "Vast.ai state change failed"),
        ("destroy", "Vast.ai destruction failed"),
        ("ssh_key", "Vast.ai SSH key creation failed"),
    ],
)
def test_vast_empty_mutation_body_requires_http_204(
    fake_http: FakeHttp,
    operation: str,
    safe_error: str,
    status_code: int,
):
    client = VastClient("vast_synthetic_secret", transport=fake_http)
    if operation == "state":
        fake_http.add_raw_response(
            method="PUT",
            url="https://console.vast.ai/api/v0/instances/4815/",
            status_code=status_code,
            body=b"",
        )
        invoke = lambda: client.set_state(4815, "stopped")
    elif operation == "destroy":
        fake_http.add_raw_response(
            method="DELETE",
            url="https://console.vast.ai/api/v0/instances/4815/",
            status_code=status_code,
            body=b"",
        )
        invoke = lambda: client.destroy_instance(
            4815, confirmed_instance_id=4815
        )
    else:
        fake_http.add_response(
            url="https://console.vast.ai/api/v0/ssh/", json={"ssh_keys": []}
        )
        fake_http.add_raw_response(
            method="POST",
            url="https://console.vast.ai/api/v0/ssh/",
            status_code=status_code,
            body=b"",
        )
        invoke = lambda: client.ensure_account_ssh_key(
            "ssh-ed25519 AAAAC3NzaEmptyFailure defend-control"
        )

    with pytest.raises(VastError) as pending:
        invoke()

    assert str(pending.value) == safe_error


def test_vast_retries_429_with_bounded_jitter_and_caps_response_size(
    fake_http: FakeHttp,
):
    search_url = "https://console.vast.ai/api/v0/bundles/"
    for _ in range(2):
        fake_http.add_response(
            method="POST",
            url=search_url,
            status_code=429,
            json={"error": "rate limited"},
        )
    fake_http.add_response(method="POST", url=search_url, json={"offers": []})
    sleeps = []
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        sleep=sleeps.append,
        jitter=lambda: 0.5,
    )

    assert client.search_offers(Decimal("2.50")) == ()
    assert len(fake_http.requests) == 3
    assert sleeps == [0.25, 0.5]

    oversized = FakeHttp()
    oversized.add_raw_response(
        method="POST", url=search_url, body=b"x" * (64 * 1024 + 1)
    )
    with pytest.raises(VastError, match="64 KiB"):
        VastClient("vast_synthetic_secret", transport=oversized).search_offers(
            Decimal("2.50")
        )


def test_vast_429_retry_is_bounded_and_headers_never_leak_credentials(
    fake_http: FakeHttp,
):
    token = "vast_synthetic_secret"
    search_url = "https://console.vast.ai/api/v0/bundles/"
    for _ in range(4):
        fake_http.add_response(
            method="POST",
            url=search_url,
            status_code=429,
            json={"error": f"private rate limit detail {token}"},
        )
    client = VastClient(
        token,
        transport=fake_http,
        sleep=lambda _seconds: None,
        jitter=lambda: 1.0,
    )

    with pytest.raises(VastError) as pending:
        client.search_offers(Decimal("2.50"))

    assert str(pending.value) == "Vast.ai request failed (status 429)"
    assert len(fake_http.requests) == 3
    for request in fake_http.requests:
        assert request.timeout == 30.0
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert token not in request.url
        assert token not in json.dumps(request.json)
        assert token not in repr(request)
    assert token not in repr(client)
    assert token not in repr(pending.value)


def test_vast_does_not_replay_create_instance_after_429(fake_http: FakeHttp):
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.98"),
    )
    create_url = "https://console.vast.ai/api/v0/asks/101/"
    fake_http.add_response(
        method="PUT", url=create_url, status_code=429, json={"error": "limited"}
    )
    fake_http.add_response(
        method="PUT",
        url=create_url,
        json={"success": True, "new_contract": 9999},
    )

    with pytest.raises(VastError, match="status 429"):
        VastClient(
            "vast_synthetic_secret",
            transport=fake_http,
            sleep=lambda _seconds: None,
        ).create_instance(offer, LaunchSpec.default())

    assert len(fake_http.requests) == 1


def test_vast_does_not_replay_ssh_key_creation_after_429(fake_http: FakeHttp):
    ssh_url = "https://console.vast.ai/api/v0/ssh/"
    public_key = "ssh-ed25519 AAAAC3NzaNoReplay defend-control"
    fake_http.add_response(url=ssh_url, json={"ssh_keys": []})
    fake_http.add_response(
        method="POST", url=ssh_url, status_code=429, json={"error": "limited"}
    )
    fake_http.add_response(
        method="POST", url=ssh_url, json={"success": True, "id": 99}
    )

    with pytest.raises(VastError, match="status 429"):
        VastClient(
            "vast_synthetic_secret",
            transport=fake_http,
            sleep=lambda _seconds: None,
        ).ensure_account_ssh_key(public_key)

    assert [(request.method, request.path) for request in fake_http.requests] == [
        ("GET", "/api/v0/ssh/"),
        ("POST", "/api/v0/ssh/"),
    ]


@pytest.mark.parametrize("operation", ["state", "destroy"])
def test_vast_retries_only_safe_idempotent_mutations_after_429(
    fake_http: FakeHttp, operation: str
):
    if operation == "state":
        method = "PUT"
        url = "https://console.vast.ai/api/v0/instances/4815/"
        invoke_name = "set_state"
    else:
        method = "DELETE"
        url = "https://console.vast.ai/api/v0/instances/4815/"
        invoke_name = "destroy_instance"
    for _ in range(2):
        fake_http.add_response(
            method=method, url=url, status_code=429, json={"error": "limited"}
        )
    fake_http.add_response(method=method, url=url, json={"success": True})
    sleeps = []
    client = VastClient(
        "vast_synthetic_secret",
        transport=fake_http,
        sleep=sleeps.append,
        jitter=lambda: 0.5,
    )

    if invoke_name == "set_state":
        result = client.set_state(4815, "stopped")
    else:
        fake_http.add_raw_response(url=url, status_code=404, body=b"")
        result = client.destroy_instance(4815, confirmed_instance_id=4815)

    assert result is True
    assert len(fake_http.requests) == (4 if operation == "destroy" else 3)
    assert sleeps == [0.25, 0.5]


@pytest.mark.parametrize("offer_id", [True, "12", "1/2", "1%2F2", 0, -1])
def test_vast_create_validates_runtime_offer_id_before_url(
    fake_http: FakeHttp, offer_id: object
):
    offer = VastOffer(
        offer_id,  # type: ignore[arg-type]
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.98"),
    )

    with pytest.raises(ValueError, match="offer ID"):
        VastClient(
            "vast_synthetic_secret", transport=fake_http
        ).create_instance(offer, LaunchSpec.default())

    assert fake_http.requests == []


def test_task5_types_are_immutable_and_launch_default_is_exact():
    launch = LaunchSpec.default()
    assert launch == LaunchSpec(
        "vllm/vllm-openai:v0.10.0",
        160,
        "ssh_direc ssh_proxy",
        "defend-vllm",
    )
    with pytest.raises(FrozenInstanceError):
        launch.disk_gb = 1  # type: ignore[misc]
