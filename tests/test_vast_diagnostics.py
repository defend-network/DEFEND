"""Vast SSH transport readiness + sanitized instance diagnostic tests.

Unit-only: no provider, no network, no billing.
"""

import json
from decimal import Decimal

from defend_control.types import LaunchSpec, VastInstance, VastOffer
from defend_control.vast_diagnostics import (
    TransportReadiness,
    build_instance_diagnostic,
)


def _instance(**overrides) -> VastInstance:
    fields = dict(
        instance_id=47793544,
        actual_status="running",
        ssh_host="ssh1.vast.ai",
        ssh_port=33544,
        gpu_name="A100 SXM4",
        gpu_ram_mb=81920,
        dph_total=Decimal("2.6711111111111108"),
        machine_id=28415,
        direct_ssh_host="203.0.113.50",
        direct_ssh_port=33544,
        image_runtype="ssh_direct",
    )
    fields.update(overrides)
    return VastInstance(**fields)


def _offer() -> VastOffer:
    return VastOffer(
        41832909,
        "A100 SXM4",
        81920,
        Decimal("2.6711111111111108"),
        Decimal("0.9994007"),
    )


class TestTransportReadiness:
    def test_states_are_explicit_and_ordered(self):
        assert [state.value for state in TransportReadiness] == [
            "provider_running",
            "direct_ssh_reachable",
            "fingerprint_observed",
            "owner_fingerprint_confirmed",
            "bootstrap",
        ]

    def test_provider_running_is_not_sshd_ready(self):
        assert TransportReadiness.PROVIDER_RUNNING.value != "ready"
        assert TransportReadiness.DIRECT_SSH_REACHABLE.value == "direct_ssh_reachable"


class TestInstanceDiagnosticRecord:
    def test_record_contains_required_sanitized_fields(self):
        record = build_instance_diagnostic(
            instance=_instance(),
            offer=_offer(),
            launch=LaunchSpec.coder_heavy_direct(),
            transport="direct",
            failure_category="ssh_unreachable",
            timestamps={
                "created_at": "2026-08-15T14:19:32+00:00",
                "destroyed_at": "2026-08-15T14:32:26+00:00",
            },
        )
        assert record["instance_id"] == 47793544
        assert record["offer_id"] == 41832909
        assert record["machine_id"] == 28415
        assert record["actual_status"] == "running"
        assert record["image"] == "vllm/vllm-openai:v0.10.0"
        assert record["requested_runtype"] == "ssh_direct"
        assert record["provider_image_runtype"] == "ssh_direct"
        assert record["ssh_direct_host_present"] is True
        assert record["ssh_direct_port_present"] is True
        assert record["ssh_proxy_host_present"] is True
        assert record["ssh_proxy_port_present"] is True
        assert record["transport_attempted"] == "direct"
        assert record["failure_category"] == "ssh_unreachable"
        assert record["timestamps"]["created_at"] == "2026-08-15T14:19:32+00:00"
        blob = json.dumps(record).casefold()
        for banned in ("api_key", "password", "secret", "bearer", "token_value"):
            assert banned not in blob

    def test_record_flags_missing_endpoints_as_absent(self):
        record = build_instance_diagnostic(
            instance=_instance(direct_ssh_host=None, direct_ssh_port=None),
            offer=_offer(),
            launch=LaunchSpec.coder_heavy_direct(),
            transport="proxy",
            failure_category="ssh_unreachable",
            timestamps={},
        )
        assert record["ssh_direct_host_present"] is False
        assert record["ssh_direct_port_present"] is False
        assert record["ssh_proxy_host_present"] is True
        assert record["ssh_proxy_port_present"] is True
        assert record["transport_attempted"] == "proxy"

    def test_record_never_echoes_secret_values(self):
        record = build_instance_diagnostic(
            instance=_instance(),
            offer=_offer(),
            launch=LaunchSpec.coder_heavy_direct(),
            transport="direct",
            failure_category="ssh_unreachable",
            timestamps={"created_at": "2026-08-15T14:19:32+00:00"},
        )
        blob = json.dumps(record)
        assert "vllm_synthetic" not in blob
        assert "hf_synthetic" not in blob

    def test_record_distinguishes_requested_from_provider_runtype(self):
        record = build_instance_diagnostic(
            instance=_instance(image_runtype="ssh_proxy"),
            offer=_offer(),
            launch=LaunchSpec.coder_heavy_direct(),
            transport="direct",
            failure_category="ssh_unreachable",
            timestamps={},
        )
        assert record["requested_runtype"] == "ssh_direct"
        assert record["provider_image_runtype"] == "ssh_proxy"