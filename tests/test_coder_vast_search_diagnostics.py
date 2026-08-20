"""Sanitized zero-spend Vast offer-search diagnostic tests.

Unit-only: fake transport, no provider, no network, no billing, no
credentials. Proves diagnostics never create instances, never dump raw
provider bodies, never leak keys, and that local validation counts
rejections without hiding valid offers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import json
from urllib.parse import urlsplit

import pytest

from defend_control.types import ResourceProfile
from defend_control.vast import (
    OFFER_REJECTION_CATEGORIES,
    VastClient,
    VastOffer,
    approved_vast_gpu_names,
)


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    json: object | None
    max_response_bytes: int = 0


@dataclass(frozen=True)
class _Response:
    status_code: int
    body: bytes


class _FakeTransport:
    def __init__(self) -> None:
        self.responses: list[_Response] = []
        self.requests: list[_Request] = []

    def add(self, *, offers: object, status_code: int = 200) -> None:
        self.responses.append(
            _Response(
                status_code,
                json.dumps({"offers": offers}).encode("utf-8"),
            )
        )

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
        assert max_response_bytes in (64 * 1024, _SEARCH_CAP)
        self.requests.append(
            _Request(method, urlsplit(url).path, json, max_response_bytes)
        )
        assert self.responses, "no fake response registered"
        return self.responses.pop(0)

    @property
    def search_calls(self) -> list[_Request]:
        return [
            request
            for request in self.requests
            if request.path == "/api/v0/bundles/"
        ]

    @property
    def create_calls(self) -> list[_Request]:
        return [
            request
            for request in self.requests
            if request.path.startswith("/api/v0/asks/")
            and request.method == "PUT"
        ]


_HEAVY = ResourceProfile(
    num_gpus=2,
    min_gpu_ram_mb=81_920,
    allowed_gpu_families=("H100", "H200", "B200"),
    min_reliability=Decimal("0.98"),
    min_disk_gb=160,
)
_KEY = "vast_synthetic_diagnostic_key"

_HEAVY_GPU_NAMES = (
    "H100 SXM",
    "H100 PCIE",
    "H100 NVL",
    "H200",
    "H200 NVL",
    "B200",
)

_SEARCH_CAP = 4 * 1024 * 1024


def _h100(offer_id: int, **overrides) -> dict:
    offer = {
        "id": offer_id,
        "gpu_name": "H100 SXM 80GB",
        "gpu_ram": 81_920,
        "disk_space": 160.0,
        "num_gpus": 2,
        "dph_total": 3.61,
        "reliability": 0.989,
        "verified": True,
        "rentable": True,
        "rented": False,
        "type": "on-demand",
    }
    offer.update(overrides)
    return offer


def _search_payload(request: _Request) -> dict:
    assert isinstance(request.json, dict)
    return request.json


class _FilteringTransport:
    """Simulates the provider's server-side gpu_name {"in": [...]} filter.

    Offers whose gpu_name is not in the requested set are never returned,
    exactly like Vast.ai scoping the universe before limit/order.
    """

    def __init__(self, offers: list[dict]) -> None:
        self.offers = list(offers)
        self.requests: list[_Request] = []

    def add(self, *, offers: object, status_code: int = 200) -> None:
        raise AssertionError("_FilteringTransport filters a fixed offer list")

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
        assert max_response_bytes in (64 * 1024, _SEARCH_CAP)
        self.requests.append(
            _Request(method, urlsplit(url).path, json, max_response_bytes)
        )
        assert isinstance(json, dict)
        requested = json.get("gpu_name", {}).get("in")
        filtered = self.offers
        if requested is not None:
            filtered = [
                offer for offer in filtered if offer["gpu_name"] in requested
            ]
        limit = int(json.get("limit", 20))
        body = globals()["json"].dumps(
            {"offers": filtered[:limit]}
        ).encode("utf-8")
        return _Response(200, body)

    @property
    def search_calls(self) -> list[_Request]:
        return [
            request
            for request in self.requests
            if request.path == "/api/v0/bundles/"
        ]

    @property
    def create_calls(self) -> list[_Request]:
        return [
            request
            for request in self.requests
            if request.path.startswith("/api/v0/asks/")
            and request.method == "PUT"
        ]


class TestSearchNeverCreates:
    def test_diagnostic_requests_are_search_only(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101), _h100(102)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(transport.search_calls) == 1
        assert transport.create_calls == []
        payload = _search_payload(transport.search_calls[0])
        assert payload["type"] == "on-demand"
        assert payload["verified"] == {"eq": True}
        assert payload["gpu_name"] == {"in": list(_HEAVY_GPU_NAMES)}
        assert payload["num_gpus"] == {"eq": 2}
        assert payload["gpu_ram"] == {"gte": 80_000}
        assert payload["reliability"] == {"gte": 0.98}
        assert payload["dph_total"] == {"lte": 4.5}
        assert payload["disk_space"] == {"gte": 160}
        assert "direct_port_count" not in payload

    def test_proxy_search_never_sends_direct_port_filter(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(
            Decimal("4.50"), _HEAVY, require_direct_ports=False
        )
        payload = _search_payload(transport.search_calls[0])
        assert "direct_port_count" not in payload

    def test_direct_search_sends_direct_port_filter(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(
            Decimal("4.50"), _HEAVY, require_direct_ports=True
        )
        payload = _search_payload(transport.search_calls[0])
        assert payload["direct_port_count"] == {"gte": 1}

    def test_ladder_proxy_mode_omits_direct_port_rung(self):
        transport = _FakeTransport()
        for _ in range(8):
            transport.add(offers=[])
        client = VastClient(_KEY, transport=transport)
        ladder = client.diagnose_filters(
            Decimal("4.50"),
            _HEAVY,
            require_direct_ports=False,
        )
        assert len(transport.search_calls) == 8
        assert "direct ports" not in dict(ladder)
        assert "disk" in dict(ladder)

    def test_heavy_search_sends_gpu_name_in_to_vast(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        payload = _search_payload(transport.search_calls[0])
        assert payload["gpu_name"] == {"in": list(_HEAVY_GPU_NAMES)}

    def test_limit_20_does_not_alter_approved_family_universe(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        payload = _search_payload(transport.search_calls[0])
        assert payload["limit"] == 20
        assert payload["gpu_name"] == {"in": list(_HEAVY_GPU_NAMES)}
        assert payload["gpu_name"]["in"] == list(_HEAVY_GPU_NAMES)

    def test_cheap_a100_cannot_occupy_limit_and_hide_expensive_h100(self):
        cheap_a100s = [
            _h100(2000 + index, gpu_name="A100 SXM4", dph_total=1.00)
            for index in range(20)
        ]
        h100 = _h100(1001, gpu_name="H100 SXM", dph_total=3.61)
        transport = _FilteringTransport(cheap_a100s + [h100])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [1001]
        assert transport.create_calls == []

    def test_search_remains_zero_spend(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(transport.search_calls) == 1
        assert transport.create_calls == []

    def test_filter_ladder_never_creates(self):
        transport = _FakeTransport()
        for offers in (
            [_h100(1)],
            [_h100(2)],
            [],
            [_h100(3)],
            [_h100(4)],
            [],
            [],
            [],
            [],
        ):
            transport.add(offers=offers)
        client = VastClient(_KEY, transport=transport)
        ladder = client.diagnose_filters(Decimal("4.50"), _HEAVY)
        assert len(transport.search_calls) == 9
        assert transport.create_calls == []
        counts = dict(ladder)
        assert counts["base ondemand"] == 1
        assert counts["base on-demand"] == 1
        assert counts["2 GPUs"] == 0
        assert counts["approved GPU names"] == 1
        assert counts["80GB class"] == 1
        assert counts["reliability"] == 0
        assert counts["price"] == 0
        assert counts["disk"] == 0
        assert counts["direct ports"] == 0

    def test_ladder_rungs_are_cumulative(self):
        transport = _FakeTransport()
        for _ in range(9):
            transport.add(offers=[])
        client = VastClient(_KEY, transport=transport)
        client.diagnose_filters(Decimal("4.50"), _HEAVY)
        steps = (
            ("num_gpus", {"eq": 2}),
            ("gpu_name", {"in": list(_HEAVY_GPU_NAMES)}),
            ("gpu_ram", {"gte": 80_000}),
            ("reliability", {"gte": 0.98}),
            ("dph_total", {"lte": 4.5}),
            ("disk_space", {"gte": 160}),
            ("direct_port_count", {"gte": 1}),
        )
        for rung_index in range(2, 9):
            payload = _search_payload(transport.search_calls[rung_index])
            for field, expected in steps[: rung_index - 1]:
                assert payload[field] == expected
            assert payload["verified"] == {"eq": True}
            assert payload["rentable"] == {"eq": True}
            assert payload["rented"] == {"eq": False}
        assert "type" not in _search_payload(transport.search_calls[8])

    def test_ladder_probes_both_type_spellings(self):
        transport = _FakeTransport()
        for _ in range(9):
            transport.add(offers=[])
        client = VastClient(_KEY, transport=transport)
        client.diagnose_filters(Decimal("4.50"), _HEAVY)
        spellings = [
            _search_payload(request)["type"]
            for request in transport.search_calls[:2]
        ]
        assert spellings == ["ondemand", "on-demand"]
        assert transport.search_calls[2].json.get("num_gpus") == {"eq": 2}
        assert transport.search_calls[3].json.get("gpu_name") == {
            "in": list(_HEAVY_GPU_NAMES)
        }
        assert transport.search_calls[4].json.get("gpu_ram") == {
            "gte": 80_000
        }
        assert transport.search_calls[5].json.get("reliability") == {
            "gte": 0.98
        }
        assert transport.search_calls[6].json.get("dph_total") == {
            "lte": 4.5
        }
        assert transport.search_calls[7].json.get("disk_space") == {
            "gte": 160
        }
        assert transport.search_calls[8].json.get("direct_port_count") == {
            "gte": 1
        }


class TestRawVersusEligible:
    def test_counts_distinguish_provider_from_eligible(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(201),
                _h100(202, dph_total=5.00),
                _h100(203, reliability=0.9),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [201]
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 3
        assert eligible == 1
        assert dict(rejections)["over_price"] == 1
        assert dict(rejections)["below_reliability"] == 1
        assert client.offer_search_summary == (
            "provider returned 3; eligible 1"
        )

    def test_realistic_two_x_h100_response_is_eligible(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                {
                    "id": 700123,
                    "gpu_name": "H100 SXM 80GB",
                    "gpu_ram": 81_920,
                    "disk_space": 160.0,
                    "num_gpus": 2,
                    "dph_total": 3.61,
                    "reliability": 0.989,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                }
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(offers) == 1
        offer = offers[0]
        assert isinstance(offer, VastOffer)
        assert offer.offer_id == 700123
        assert offer.gpu_name == "H100 SXM 80GB"
        assert offer.gpu_ram_mb == 81_920
        assert offer.dph_total == Decimal("3.61")
        assert offer.reliability == Decimal("0.989")

    def test_malformed_one_offer_hides_none(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(301),
                {
                    "id": "not-an-id",
                    "gpu_name": "H100 SXM 80GB",
                    "gpu_ram": "garbage",
                    "disk_space": None,
                    "num_gpus": "two",
                    "dph_total": "free",
                },
                _h100(303),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [301, 303]
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 3
        assert eligible == 2
        assert dict(rejections)["malformed_numeric_field"] == 1

    def test_boundary_price_at_ceiling_is_eligible(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(401, dph_total=4.50)])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(offers) == 1
        assert offers[0].dph_total == Decimal("4.50")


class TestRejectionCategories:
    def test_each_category_counts_once(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(1, verified=False),
                _h100(2, rentable=False),
                _h100(3, rented=True),
                _h100(4, type="bid"),
                _h100(5, num_gpus=1),
                _h100(6, gpu_ram=40_000),
                _h100(7, disk_space=100),
                _h100(8, gpu_name="A100 SXM4"),
                _h100(9, reliability=0.5),
                _h100(10, dph_total=9.99),
                _h100(11, dph_total="broken"),
                "not-a-mapping",
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 12
        assert eligible == 0
        counted = dict(rejections)
        assert counted["not_verified"] == 1
        assert counted["not_rentable"] == 1
        assert counted["already_rented"] == 1
        assert counted["wrong_pricing_type"] == 1
        assert counted["wrong_gpu_count"] == 1
        assert counted["insufficient_vram"] == 1
        assert counted["insufficient_disk"] == 1
        assert counted["wrong_gpu_family"] == 1
        assert counted["below_reliability"] == 1
        assert counted["over_price"] == 1
        assert counted["malformed_numeric_field"] == 1
        assert counted["invalid_shape"] == 1

    def test_categories_are_exactly_the_whitelist(self):
        assert OFFER_REJECTION_CATEGORIES == (
            "invalid_shape",
            "not_verified",
            "not_rentable",
            "already_rented",
            "wrong_pricing_type",
            "wrong_gpu_count",
            "insufficient_vram",
            "insufficient_disk",
            "wrong_gpu_family",
            "below_reliability",
            "below_cuda_max",
            "over_price",
            "malformed_numeric_field",
        )


class TestCudaCapabilityFilter:
    def test_search_sends_cuda_filter_when_profile_requires(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        profile = replace(_HEAVY, min_cuda_max_good=13.0)
        client.search_offers(Decimal("4.50"), profile)
        payload = _search_payload(transport.search_calls[0])
        assert payload["cuda_max_good"] == {"gte": 13.0}

    def test_search_omits_cuda_filter_when_unset(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(101)])
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        payload = _search_payload(transport.search_calls[0])
        assert "cuda_max_good" not in payload

    def test_offer_below_cuda_floor_is_rejected_and_counted(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(102, cuda_max_good=12.2),
                _h100(103, cuda_max_good=13.0),
                _h100(104),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(
            Decimal("4.50"),
            replace(_HEAVY, min_cuda_max_good=13.0),
        )
        assert [offer.offer_id for offer in offers] == [103, 104]
        assert offers[0].cuda_max_good == 13.0
        assert offers[1].cuda_max_good is None
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 3
        assert eligible == 2
        assert dict(rejections)["below_cuda_max"] == 1

    def test_malformed_cuda_max_good_is_rejected_as_malformed(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(105, cuda_max_good="13.0.0")])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(
            Decimal("4.50"),
            replace(_HEAVY, min_cuda_max_good=13.0),
        )
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert dict(rejections)["malformed_numeric_field"] == 1

    def test_cuda_boundary_exactly_at_floor_is_eligible(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(106, cuda_max_good=13.0)])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(
            Decimal("4.50"),
            replace(_HEAVY, min_cuda_max_good=13.0),
        )
        assert [offer.offer_id for offer in offers] == [106]


class TestApprovedGpuUniverse:
    @pytest.mark.parametrize(
        "gpu_name",
        ["H100 SXM", "H100 PCIE", "H100 NVL", "H200 SXM", "H200 NVL", "B200"],
    )
    def test_approved_variant_is_eligible(self, gpu_name):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(1, gpu_name=gpu_name, dph_total=3.61)
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(offers) == 1
        assert offers[0].gpu_name == gpu_name

    def test_wrong_family_still_rejected_locally_as_defense(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(1, gpu_name="A100 SXM4", dph_total=1.00)])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 1
        assert eligible == 0
        assert dict(rejections)["wrong_gpu_family"] == 1

    def test_approved_mapping_covers_default_and_coder_profiles(self):
        from defend_control.vast import approved_vast_gpu_names

        names = approved_vast_gpu_names(("A100", "H100", "H200", "B200"))
        assert "A100 SXM4" in names
        assert "A100 PCIE" in names
        for name in _HEAVY_GPU_NAMES:
            assert name in names

    def test_unknown_family_fails_closed(self):
        from defend_control.vast import approved_vast_gpu_names

        with pytest.raises(ValueError):
            approved_vast_gpu_names(("H100", "GH200"))

    def test_variants_belong_to_their_family(self):
        from defend_control.vast import VAST_GPU_NAME_VARIANTS

        for family, variants in VAST_GPU_NAME_VARIANTS.items():
            for variant in variants:
                assert variant.upper().startswith(family.upper())


class TestAbsentEchoFieldsAreNotRejections:
    def test_missing_verified_rentable_rented_type_reliability_ok(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                {
                    "id": 501,
                    "gpu_name": "H100 SXM 80GB",
                    "gpu_ram": 81_920,
                    "disk_space": 160.0,
                    "num_gpus": 2,
                    "dph_total": 3.61,
                }
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(offers) == 1
        assert offers[0].offer_id == 501
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 1
        assert eligible == 1
        assert rejections == ()

    def test_explicit_non_verified_string_still_rejected(self):
        offer = _h100(601)
        del offer["verified"]
        offer["verification"] = "unverified"
        transport = _FakeTransport()
        transport.add(offers=[offer])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert dict(rejections)["not_verified"] == 1

    def test_integral_float_numerics_are_accepted(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                {
                    "id": 701.0,
                    "gpu_name": "H100 SXM 80GB",
                    "gpu_ram": 81_920.0,
                    "disk_space": 160.0,
                    "num_gpus": 2.0,
                    "dph_total": 3.61,
                    "reliability": 0.989,
                    "verified": True,
                    "rentable": True,
                    "rented": False,
                    "type": "on-demand",
                }
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert len(offers) == 1
        assert offers[0].offer_id == 701

    def test_fractional_gpu_count_is_rejected(self):
        transport = _FakeTransport()
        transport.add(offers=[_h100(801, num_gpus=2.5)])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert dict(rejections)["malformed_numeric_field"] == 1


class TestNoSecretsNoRawBodies:
    def test_api_key_never_appears_in_diagnostics(self):
        transport = _FakeTransport()
        for _ in range(10):
            transport.add(offers=[_h100(1)])
        client = VastClient(_KEY, transport=transport)
        client.diagnose_filters(Decimal("4.50"), _HEAVY)
        client.search_offers(Decimal("4.50"), _HEAVY)
        provider, eligible, rejections = client.last_search_counts()
        outputs = [
            repr(client),
            client.offer_search_summary,
            str(provider),
            str(eligible),
            str(rejections),
            client.last_raw_payload("create") is None,
        ]
        blob = " | ".join(
            output if isinstance(output, str) else str(output)
            for output in outputs
        )
        assert _KEY not in blob
        assert "api_key" not in blob.casefold()

    def test_diagnostic_output_contains_no_raw_provider_body(self):
        transport = _FakeTransport()
        for _ in range(9):
            transport.add(
                offers=[
                    _h100(1, gpu_name="H100 SXM 80GB", dph_total=3.61)
                ]
            )
        client = VastClient(_KEY, transport=transport)
        ladder = client.diagnose_filters(Decimal("4.50"), _HEAVY)
        assert all(
            isinstance(label, str) and isinstance(count, int)
            for label, count in ladder
        )
        assert "H100 SXM 80GB" not in client.offer_search_summary
        assert "3.61" not in client.offer_search_summary

    def test_summary_and_counts_contain_no_provider_payloads(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                _h100(1, gpu_name="H100 SXM 80GB", dph_total=3.61),
                _h100(2, dph_total=9.99),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        client.search_offers(Decimal("4.50"), _HEAVY)
        provider, eligible, rejections = client.last_search_counts()
        blob = json.dumps(
            {
                "summary": client.offer_search_summary,
                "provider": provider,
                "eligible": eligible,
                "rejections": rejections,
            }
        )
        assert "H100 SXM 80GB" not in blob
        assert "3.61" not in blob
        assert "9.99" not in blob


class _FakeDiagnosticClient:
    def __init__(self) -> None:
        self.diagnosed = False
        self.searched = False

    def discover_gpu_names(self, *, num_gpus):
        return (
            ("H100 SXM", 2, Decimal("3.5756"), 81559, Decimal("0.996388")),
            ("A100 SXM4", 7, Decimal("1.6014"), 81920, Decimal("0.998886")),
        )

    def exact_name_counts(self, names):
        return tuple((name, 1 if name == "H100 SXM" else 0) for name in names)

    def probe_type_semantics(self):
        return (20, 20, 20)

    def approved_offer_details(self, profile):
        return (
            (
                44302087,
                "H100 SXM",
                81559,
                2,
                Decimal("0.9890523"),
                Decimal("3.5756"),
                Decimal("166.5"),
                256,
            ),
        )

    def diagnose_filters(self, ceiling, profile, *, require_direct_ports=True):
        del require_direct_ports
        self.diagnosed = True
        return (
            ("base ondemand", 20),
            ("base on-demand", 20),
            ("2 GPUs", 20),
            ("approved GPU names", 13),
            ("80GB class", 5),
            ("reliability", 4),
            ("price", 0),
            ("disk", 0),
            ("direct ports", 0),
        )

    def search_offers(self, ceiling, profile, *, require_direct_ports=False):
        del require_direct_ports
        self.searched = True
        return (VastOffer(1, "H100 SXM", 81920, Decimal("3.61"), Decimal("0.989")),)

    def last_search_counts(self):
        return (20, 1, (("wrong_gpu_family", 19),))


class TestCapturedLiveShapes:
    """Realistic response shapes captured from the live REST API.

    H100 80GB-class reports gpu_ram 81559 MB; search responses omit the
    type field; the H200 family's name is exactly "H200".
    """

    _H100_SXM = {
        "id": 44302087,
        "gpu_name": "H100 SXM",
        "gpu_ram": 81559,
        "disk_space": 166.5,
        "num_gpus": 2,
        "dph_total": 3.5756,
        "reliability": 0.9890523,
        "direct_port_count": 256,
        "verified": True,
        "rentable": True,
        "rented": False,
    }
    _H100_PCIE = {
        "id": 46096699,
        "gpu_name": "H100 PCIE",
        "gpu_ram": 81559,
        "disk_space": 194.4,
        "num_gpus": 2,
        "dph_total": 3.7356,
        "reliability": 0.9898909,
        "direct_port_count": 256,
        "verified": True,
        "rentable": True,
        "rented": False,
    }
    _A100 = {
        "id": 404,
        "gpu_name": "A100 SXM4",
        "gpu_ram": 81920,
        "disk_space": 500.0,
        "num_gpus": 2,
        "dph_total": 1.60,
        "reliability": 0.998,
        "direct_port_count": 64,
        "verified": True,
        "rentable": True,
        "rented": False,
    }

    def test_discovery_returns_sanitized_aggregates_only(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                dict(self._H100_SXM),
                dict(self._H100_SXM, id=44302088, dph_total=6.1387),
                dict(self._H100_PCIE),
                dict(self._A100),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        aggregates = client.discover_gpu_names(num_gpus=2)
        by_name = dict(
            (name, (count, min_dph, max_ram, max_rel))
            for name, count, min_dph, max_ram, max_rel in aggregates
        )
        assert by_name["H100 SXM"] == (
            2,
            Decimal("3.5756"),
            81559,
            Decimal("0.9890523"),
        )
        assert by_name["H100 PCIE"] == (
            1,
            Decimal("3.7356"),
            81559,
            Decimal("0.9898909"),
        )
        assert by_name["A100 SXM4"] == (
            1,
            Decimal("1.6"),
            81920,
            Decimal("0.998"),
        )
        blob = str(aggregates)
        assert "44302087" not in blob
        assert _KEY not in blob
        assert transport.create_calls == []

    def test_discovery_uses_search_response_cap(self):
        transport = _FakeTransport()
        transport.add(offers=[dict(self._H100_SXM)])
        client = VastClient(_KEY, transport=transport)
        client.discover_gpu_names(num_gpus=2, limit=100)
        assert transport.search_calls[0].json["limit"] == 100
        assert transport.requests[0].max_response_bytes == _SEARCH_CAP

    def test_exact_name_counts_probes_each_name_individually(self):
        transport = _FakeTransport()
        transport.add(offers=[dict(self._H100_SXM)])
        transport.add(offers=[])
        transport.add(offers=[])
        client = VastClient(_KEY, transport=transport)
        counts = client.exact_name_counts(
            ("H100 SXM", "H100 PCIE", "H200")
        )
        assert counts == (("H100 SXM", 1), ("H100 PCIE", 0), ("H200", 0))
        for name, request in zip(
            ("H100 SXM", "H100 PCIE", "H200"),
            transport.search_calls,
        ):
            assert request.json.get("gpu_name") == {"eq": name}

    def test_type_semantics_probe_sends_all_three_documents(self):
        transport = _FakeTransport()
        for _ in range(3):
            transport.add(offers=[dict(self._H100_SXM)])
        client = VastClient(_KEY, transport=transport)
        result = client.probe_type_semantics()
        assert result == (1, 1, 1)
        documents = [
            request.json for request in transport.search_calls
        ]
        assert "type" not in documents[0]
        assert documents[1]["type"] == "ondemand"
        assert documents[2]["type"] == "on-demand"
        assert documents[0]["num_gpus"] == {"eq": 2}

    def test_approved_offer_details_captured_shape(self):
        transport = _FakeTransport()
        transport.add(offers=[dict(self._H100_PCIE), dict(self._H100_SXM)])
        client = VastClient(_KEY, transport=transport)
        details = client.approved_offer_details(_HEAVY)
        assert details == (
            (
                44302087,
                "H100 SXM",
                81559,
                2,
                Decimal("0.9890523"),
                Decimal("3.5756"),
                Decimal("166.5"),
                256,
            ),
            (
                46096699,
                "H100 PCIE",
                81559,
                2,
                Decimal("0.9898909"),
                Decimal("3.7356"),
                Decimal("194.4"),
                256,
            ),
        )
        blob = str(details)
        assert _KEY not in blob
        assert "verified" not in blob

    def test_captured_h100_offer_qualifies_under_80gb_class_threshold(self):
        transport = _FakeTransport()
        transport.add(offers=[dict(self._H100_SXM)])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [44302087]
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 1
        assert eligible == 1
        assert dict(rejections).get("insufficient_vram", 0) == 0

    def test_80000_qualifies_and_79999_fails(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                dict(self._H100_SXM, id=5001, gpu_ram=80_000),
                dict(self._H100_SXM, id=5002, gpu_ram=79_999),
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [5001]
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 2
        assert eligible == 1
        assert dict(rejections)["insufficient_vram"] == 1

    def test_captured_pcie_offer_with_low_reliability_is_rejected(self):
        transport = _FakeTransport()
        transport.add(
            offers=[
                dict(
                    self._H100_PCIE,
                    id=46095099,
                    gpu_ram=81559,
                    dph_total=4.2689,
                    reliability=0.9676,
                )
            ]
        )
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert offers == ()
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 1
        assert eligible == 0
        assert dict(rejections)["below_reliability"] == 1
        assert dict(rejections).get("insufficient_vram", 0) == 0

    def test_vast_gpu_ram_floor_encodes_only_the_80gb_class_band(self):
        from defend_control.vast import vast_gpu_ram_floor

        assert vast_gpu_ram_floor(64_000) == 64_000
        assert vast_gpu_ram_floor(80_000) == 80_000
        assert vast_gpu_ram_floor(81_920) == 80_000
        assert vast_gpu_ram_floor(140_000) == 140_000

    def test_search_response_without_type_field_is_eligible(self):
        transport = _FakeTransport()
        offer = dict(self._H100_SXM)
        del offer["verified"]
        del offer["rentable"]
        del offer["rented"]
        transport.add(offers=[offer])
        client = VastClient(_KEY, transport=transport)
        offers = client.search_offers(Decimal("4.50"), _HEAVY)
        assert [offer.offer_id for offer in offers] == [44302087]
        provider, eligible, rejections = client.last_search_counts()
        assert provider == 1
        assert eligible == 1
        assert dict(rejections) == {}


class TestCliDiagnostic:
    def test_cli_authenticated_output_redacts_key_and_reports_ladder(
        self, monkeypatch, capsys
    ):
        import tools.defend_coder_vast_diagnose as diagnose

        fake_client = _FakeDiagnosticClient()
        monkeypatch.setattr(diagnose, "_load_api_key", lambda: _KEY)
        monkeypatch.setattr(diagnose, "VastClient", lambda key: fake_client)
        code = diagnose.run_diagnostic()
        assert code == 0
        assert fake_client.diagnosed
        assert fake_client.searched
        out = capsys.readouterr().out
        assert _KEY not in out
        assert "Authenticated: YES" in out
        assert "API key: [redacted]" in out
        assert "Qualification lane: ssh_proxy" in out
        assert "Direct ports: NOT required (proxy lane)" in out
        assert "Configured max $/hr: $4.50" in out
        assert "Required GPUs: 2" in out
        assert "Required families: H100/H200/B200" in out
        assert "GPU memory class: >= 80 GB" in out
        assert "Vast threshold: >= 80000 MB" in out
        assert "Reliability: >= 0.98" in out
        assert "Disk: >= 160 GB" in out
        assert "GPU-name discovery" in out
        assert "H100 SXM" in out
        assert "[approved]" in out
        assert "Exact approved-name match counts" in out
        assert "Type-semantics" in out
        assert "no type" in out
        assert "Approved-universe offer details" in out
        assert "44302087" in out
        assert "base ondemand" in out
        assert "approved GPU names" in out
        assert "direct ports" in out
        assert "Provider query matched approved GPU universe: 20" in out
        assert "Eligible after local validation: 1" in out
        assert "Rejected wrong_gpu_family: 19" in out

    def test_cli_direct_lane_reports_direct_ports_required(
        self, monkeypatch, capsys
    ):
        import tools.defend_coder_vast_diagnose as diagnose

        fake_client = _FakeDiagnosticClient()
        monkeypatch.setattr(diagnose, "_load_api_key", lambda: _KEY)
        monkeypatch.setattr(diagnose, "VastClient", lambda key: fake_client)
        code = diagnose.run_diagnostic(runtype="ssh_direct")
        assert code == 0
        out = capsys.readouterr().out
        assert "Qualification lane: ssh_direct" in out
        assert "Direct ports: required (>= 1)" in out

    def test_cli_rejects_invalid_runtype(self, capsys):
        import tools.defend_coder_vast_diagnose as diagnose

        code = diagnose.run_diagnostic(runtype="ssh_sidecar")
        assert code == 2
        assert "runtype must be ssh_proxy or ssh_direct" in capsys.readouterr().out

    def test_cli_unauthenticated_skips_network(self, monkeypatch, capsys):
        import tools.defend_coder_vast_diagnose as diagnose

        monkeypatch.setattr(diagnose, "_load_api_key", lambda: None)
        code = diagnose.run_diagnostic()
        assert code == 0
        out = capsys.readouterr().out
        assert "Authenticated: NO" in out
        assert "Skipping live requests" in out
        assert "Configured max $/hr: $4.50" in out

    def test_cli_surfaces_ladder_failure(self, monkeypatch, capsys):
        import tools.defend_coder_vast_diagnose as diagnose

        def fail_ladder(ceiling, profile, *, require_direct_ports=True):
            del require_direct_ports
            raise RuntimeError("boom")

        fake_client = _FakeDiagnosticClient()
        fake_client.diagnose_filters = fail_ladder
        monkeypatch.setattr(diagnose, "_load_api_key", lambda: _KEY)
        monkeypatch.setattr(diagnose, "VastClient", lambda key: fake_client)
        code = diagnose.run_diagnostic()
        assert code == 2
        out = capsys.readouterr().out
        assert "Filter ladder failed: boom" in out