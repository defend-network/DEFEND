"""Product-independent runtime registry and reserved port policy."""

from __future__ import annotations

from pathlib import Path

from defend_control.product_runtime import (
    PRODUCT_API_PORTS,
    PRODUCT_FORWARD_PORTS,
    ProductRuntimeRecord,
    ProductRuntimeRegistry,
)


def test_reserved_model_forward_ports_are_unique_per_product():
    assert PRODUCT_FORWARD_PORTS["defend-ai"] == 8402
    assert PRODUCT_FORWARD_PORTS["defendcoder"] == 8403
    assert PRODUCT_FORWARD_PORTS["defendmarkets"] == 8404
    assert PRODUCT_FORWARD_PORTS["scs-ai"] == 8405
    forward_values = list(PRODUCT_FORWARD_PORTS.values())
    assert len(set(forward_values)) == len(forward_values)


def test_product_api_ports_do_not_collide_with_admin_or_web():
    assert 8000 not in PRODUCT_API_PORTS.values()
    assert 3000 not in PRODUCT_API_PORTS.values()
    assert PRODUCT_API_PORTS["defend-ai"] == 8401


def test_registry_persists_stop_preserving_retained_fields(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update(
        "defend-ai",
        state="ready",
        provider="vast",
        instance_id=48403815,
        gpu="H200",
        gpu_ram_mb=143771,
        hourly_compute_cost="3.40",
        model_forward_port=8402,
        product_api_port=8401,
    )

    reloaded = ProductRuntimeRegistry(tmp_path / "product-runtime.json").load()
    record = reloaded["defend-ai"]
    assert record.state == "ready"
    assert record.instance_id == 48403815
    assert record.gpu == "H200"
    assert record.model_forward_port == 8402


def test_registry_update_rejects_unknown_product_or_field(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    try:
        registry.update("unknown-product")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown product must be rejected")
    try:
        registry.update("defend-ai", not_a_field=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown runtime field must be rejected")


def test_default_records_are_stopped(tmp_path):
    records = ProductRuntimeRegistry(tmp_path / "product-runtime.json").load()
    assert set(records) == {
        "defend-ai",
        "defendcoder",
        "defendmarkets",
        "scs-ai",
    }
    assert all(record.state == "stopped" for record in records.values())


def test_reconcile_clears_stale_retained_instance(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", state="stopped_retained", instance_id=48403815)
    cleared = registry.reconcile_instance(
        "defend-ai", lambda instance_id: False
    )
    record = registry.load()["defend-ai"]
    assert cleared is True
    assert record.instance_id is None
    assert record.state == "stopped"
    assert record.provider_instance_state == "missing"


def test_reconcile_keeps_retained_instance_that_still_exists(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", state="stopped_retained", instance_id=48403815)
    cleared = registry.reconcile_instance(
        "defend-ai", lambda instance_id: True
    )
    record = registry.load()["defend-ai"]
    assert cleared is False
    assert record.instance_id == 48403815
    assert record.state == "stopped_retained"


def test_record_stopped_is_retained_only_when_instance_known(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", instance_id=48403815)
    registry.record_stopped("defend-ai")
    assert registry.load()["defend-ai"].state == "stopped_retained"

    registry.update("defendcoder", instance_id=None)
    registry.record_stopped("defendcoder")
    assert registry.load()["defendcoder"].state == "stopped"


def test_record_destroyed_requires_exact_id_and_clears_instance(tmp_path):
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", state="stopped_retained", instance_id=48403815)
    try:
        registry.record_destroyed("defend-ai", 999)
    except ValueError:
        pass
    else:
        raise AssertionError("destroy with wrong instance ID must be rejected")

    registry.record_destroyed("defend-ai", 48403815)
    record = registry.load()["defend-ai"]
    assert record.instance_id is None
    assert record.state == "stopped"
    assert record.provider_instance_state == "destroyed"
