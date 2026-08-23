import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "docs" / "provider-contracts"

REQUIRED_KEYS = [
    "auth_scheme",
    "capability_summary",
    "contract_type",
    "provider_id",
    "retrieved_at",
    "source_url_or_origin",
]

ARTIFACT_SUFFIXES = {
    "oddspapi": ("oddspapi-empirical-2026-08-20.json",),
    "rapidapi_tt_micro": ("rapidapi_tt_micro-openapi.json",),
    "sportradar_tt": ("sportradar_tt-schema.zip", "sportradar_tt-official_docs.md"),
    "sports_game_odds": ("sports_game_odds-official_docs.txt", "sports_game_odds-sdk.md"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    manifests = sorted(CONTRACTS.glob("*.contract.json"))
    failures: list[str] = []
    results: list[dict] = []
    for manifest in manifests:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        provider = doc.get("provider_id", manifest.stem)
        row = {"manifest": manifest.name, "provider_id": provider}
        missing = [k for k in REQUIRED_KEYS if doc.get(k) in (None, "")]
        if missing:
            failures.append(f"{manifest.name}: missing {missing}")
            row["missing_keys"] = missing
        if doc.get("sha256"):
            artifact_name = ARTIFACT_SUFFIXES.get(provider, ())[0] if ARTIFACT_SUFFIXES.get(provider) else None
            if artifact_name:
                candidate = CONTRACTS / artifact_name
                if not candidate.exists():
                    failures.append(f"{manifest.name}: sha256 target {artifact_name} missing")
                    row["hash_status"] = "TARGET_MISSING"
                else:
                    actual = sha256(candidate)
                    ok = actual == doc["sha256"]
                    row["hash_status"] = "PASS" if ok else f"FAIL (declared {doc['sha256'][:12]}... actual {actual[:12]}...)"
                    if not ok:
                        failures.append(f"{manifest.name}: sha256 mismatch for {artifact_name}")
            else:
                row["hash_status"] = "TARGET_UNMAPPED"
        else:
            row["hash_status"] = "NOT_DECLARED"
        for suffix in ARTIFACT_SUFFIXES.get(provider, ()):
            if not (CONTRACTS / suffix).exists():
                failures.append(f"{manifest.name}: referenced artifact {suffix} missing")
                row["artifact_missing"] = suffix
        results.append(row)

    for r in sorted(results, key=lambda r: r["provider_id"]):
        print(f"{r['provider_id']:28} keys={'OK' if 'missing_keys' not in r else 'MISSING'} "
              f"hash={r.get('hash_status', '-')} artifacts={'OK' if 'artifact_missing' not in r else r['artifact_missing']}")
    print(f"\nmanifests={len(manifests)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())