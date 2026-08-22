"""M5 persistent production champion registration with fail-closed protection.

The champion row is idempotent: absent -> insert, identical -> no-op,
conflicting identity/hash or multiple champions -> FAIL_CLOSED. M5 weights are
never touched.
"""

from __future__ import annotations

from typing import Any


class ChampionConflictError(RuntimeError):
    pass


def ensure_champion(
    store: Any,
    *,
    weights_doc: dict[str, Any],
    artifact_path: str,
    artifact_sha256: str,
    feature_schema_version: int = 1,
) -> dict[str, Any]:
    model_id = str(weights_doc["model_id"])
    sha = str(weights_doc["sha256"])
    model_version = f"{model_id}:{sha[:12]}"
    fit_n = int(weights_doc["fit_n"])
    cutoff = str(weights_doc["cutoff"])

    champions = store.list_champions()
    if len(champions) > 1:
        raise ChampionConflictError(
            f"multiple champion rows present ({len(champions)}); refusing to proceed"
        )
    if champions:
        current = champions[0]
        current_version = str(current["model_version"])
        current_hash = str(current["artifact_sha256"] or "")
        if current_version == model_version and current_hash == artifact_sha256:
            return {"status": "NOOP", "model_id": model_id, "model_version": model_version}
        raise ChampionConflictError(
            f"champion identity conflict: existing {current_version}/{current_hash[:12]} "
            f"!= configured {model_version}/{artifact_sha256[:12]}; refusing to overwrite"
        )

    store.register_champion(
        model_id=model_id,
        model_version=model_version,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        fit_n=fit_n,
        cutoff=cutoff,
        feature_schema_version=feature_schema_version,
        promotion_provenance="frozen M5 artifact; owner production promotion",
        dataset_provenance="tt_match_results source_provider=odds_api_io pre-cutoff",
    )
    return {"status": "INSERTED", "model_id": model_id, "model_version": model_version}
