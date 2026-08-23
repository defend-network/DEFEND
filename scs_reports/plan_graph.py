"""MechanicalPlanGraph (M1.2, P26/P27/P53/P63).

The principal semantic design artifact. Richer than DesignBasis but feeds the
SAME downstream report pipeline. Every relationship carries evidence[],
confidence and source. Graph validation surfaces dangling entities, unresolved
references and duplicate/conflicting IDs - never silent destructive merges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MECHANICAL_PLAN_GRAPH_SCHEMA_VERSION = 1
GRAPH_EXTRACTION_VERSION = "graph-v1"

RELATIONSHIP_TYPES = {
    "SERVES", "SUPPLIES", "RETURNS_FROM", "EXHAUSTS_FROM", "CONNECTED_TO",
    "UPSTREAM_OF", "DOWNSTREAM_OF", "CONTROLLED_BY", "SENSED_BY",
    "INTERLOCKED_WITH", "DAMPER_ON", "LOCATED_IN", "PENETRATES", "REFERENCES",
    "SCHEDULED_AS", "HAS_NOTE", "HAS_DETAIL", "BALANCED_BY",
}


@dataclass
class Relationship:
    source: str
    target: str
    rel_type: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "HIGH"
    source_ref: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target,
                "rel_type": self.rel_type, "evidence": self.evidence,
                "confidence": self.confidence, "source_ref": self.source_ref}


@dataclass
class MechanicalPlanGraph:
    packet: dict[str, Any]
    sheets: list[dict[str, Any]] = field(default_factory=list)
    legends: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    schedules: list[dict[str, Any]] = field(default_factory=list)
    equipment: list[dict[str, Any]] = field(default_factory=list)
    systems: list[dict[str, Any]] = field(default_factory=list)
    duct_segments: list[dict[str, Any]] = field(default_factory=list)
    air_devices: list[dict[str, Any]] = field(default_factory=list)
    dampers: list[dict[str, Any]] = field(default_factory=list)
    controls: list[dict[str, Any]] = field(default_factory=list)
    rooms: list[dict[str, Any]] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    design_totals: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    missing_context: list[dict[str, Any]] = field(default_factory=list)
    review_items: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = MECHANICAL_PLAN_GRAPH_SCHEMA_VERSION
    extraction_version: str = GRAPH_EXTRACTION_VERSION

    # ---- relationships -----------------------------------------------------

    def relate(self, source: str, target: str, rel_type: str, *,
               evidence: list[dict[str, Any]] | None = None,
               confidence: str = "HIGH",
               source_ref: dict[str, Any] | None = None) -> None:
        self.relationships.append(Relationship(
            source, target, rel_type, evidence or [],
            confidence, source_ref,
        ))

    def relationships_of(self, entity_id: str, rel_type: str | None = None) -> list[Relationship]:
        return [r for r in self.relationships if r.source == entity_id
                and (rel_type is None or r.rel_type == rel_type)]

    def count(self, kind: str) -> int:
        return sum(1 for e in self.equipment if e.get("kind") == kind) if kind == "equipment" \
            else len(getattr(self, kind, []))

    # ---- validation (P53) --------------------------------------------------

    def validate(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        entity_ids = set()
        for kind in ("equipment", "systems", "duct_segments", "air_devices",
                     "dampers", "controls", "rooms", "zones", "notes"):
            for entity in getattr(self, kind, []):
                entity_ids.add(entity["id"])
        # duplicate ids across kinds (e.g. SD-1 diffuser type vs smoke damper)
        seen: dict[str, list[str]] = {}
        for kind in ("equipment", "systems", "duct_segments", "air_devices",
                     "dampers", "controls", "rooms", "zones"):
            for entity in getattr(self, kind, []):
                seen.setdefault(entity["id"], []).append(kind)
        for entity_id, kinds in seen.items():
            if len(kinds) > 1:
                issues.append({
                    "kind": "DUPLICATE_ENTITY_ID",
                    "detail": f"{entity_id} appears as {', '.join(kinds)}",
                    "entity_id": entity_id,
                })
        # dangling relationship references
        for rel in self.relationships:
            if rel.source not in entity_ids:
                issues.append({"kind": "DANGLING_RELATIONSHIP",
                               "detail": f"source {rel.source} missing",
                               "entity_id": rel.source})
            if rel.target not in entity_ids:
                issues.append({"kind": "DANGLING_RELATIONSHIP",
                               "detail": f"target {rel.target} missing",
                               "entity_id": rel.target})
        # unresolved sheet references
        packet_sheets = {s.get("sheet_number") for s in self.sheets}
        for ref in self.references:
            target = ref.get("target_sheet")
            if target and target not in packet_sheets and ref.get("target_present") is False:
                issues.append({"kind": "UNRESOLVED_REFERENCE",
                               "detail": f"{ref['id']} -> {target} not supplied",
                               "entity_id": ref["id"]})
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "extraction_version": self.extraction_version,
            "packet": self.packet,
            "sheets": self.sheets,
            "legends": self.legends,
            "symbols": self.symbols,
            "schedules": self.schedules,
            "equipment": self.equipment,
            "systems": self.systems,
            "duct_segments": self.duct_segments,
            "air_devices": self.air_devices,
            "dampers": self.dampers,
            "controls": self.controls,
            "rooms": self.rooms,
            "zones": self.zones,
            "notes": self.notes,
            "references": self.references,
            "relationships": [r.to_dict() for r in self.relationships],
            "design_totals": self.design_totals,
            "conflicts": self.conflicts,
            "missing_context": self.missing_context,
            "review_items": self.review_items,
        }
