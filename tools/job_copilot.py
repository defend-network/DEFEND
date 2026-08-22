"""SCS Job Copilot - Monday-ready local field copilot.

Wraps the scs_reports pipeline (JobStore, PhotoIngest, planner, composer,
validation, completeness, natural-language measurement capture) behind a
small local server + single-page UI:

    JOB  CHAT  PHOTOS  MEASUREMENTS  COMPLETENESS  REPORT PLAN  FINDINGS  GENERATE

The owner never edits JobRecord JSON by hand; natural language becomes
structured facts. Reports are composed from the immutable owner masters
(never written to) and downloaded as .xlsx.

Usage:
    python tools/job_copilot.py [--port 3220] [--workspace C:/SCS_DATA/copilot]
                                [--masters C:/SCS_DATA/masters]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scs_reports.completeness import evaluate, ready_to_leave
from scs_reports.corrections import (
    apply_known_correction,
    load_corrections,
    save_correction,
)
from scs_reports.composer import Composer
from scs_reports.nl_parse import merge_capture, parse_measurements
from scs_reports.planner import plan_for
from scs_reports.preengineer import (
    build_preengineered_record,
    design_vs_field,
    field_test_plan,
)
from scs_reports.schema import (
    AirDevice,
    Equipment,
    EquipmentType,
    Finding,
    JobMetadata,
    JobRecord,
    PhotoEvidence,
)
from scs_reports.store import JobStore, MasterStore, PhotoIngest, ReportPaths
from scs_reports.validation import validate_report

try:
    import fitz  # PyMuPDF for plan-region preview
except Exception:  # pragma: no cover
    fitz = None

from scs_reports.plans import (
    cached_basis,
    index_pdf,
    run_document,
    sha256_of,
)
from scs_reports.plan_packet import build_packet, classify_missing_context
from scs_reports.plan_semantics import build_graph, graph_to_design_basis
from scs_reports.plan_scope import (
    answer_graph_question,
    field_plan,
    scope_relevant,
)
from scs_reports.blueprint_raster import (
    cached_blueprint,
    _ocr_with_orientation,
)
from scs_reports.vision import (
    build_document_reader,
    document_reader_status,
    vision_provider_status,
)

SCOPE_MARKERS = ("scope", "verification", "verifying", "airflow", "balance",
                 "ductwork", "ducts", "outlets", "studios", "traverse",
                 "static")


def detect_scope(text: str) -> tuple[str, str]:
    """Return (report_type, scope_notes) from a natural scope description."""
    low = text.lower()
    if any(w in low for w in ("airflow", "verification", "balance", "outlet",
                              "duct", "studio")):
        report_type = "AIRFLOW_VERIFICATION"
    elif any(w in low for w in ("tab", "traverse", "vav")):
        report_type = "TAB"
    else:
        report_type = "TAB"
    return report_type, text.strip()


def _room_from_question(upper: str) -> str | None:
    match = re.search(r"(WORKOUT STUDIO [A-Z]|STUDIO [A-Z]|SPIN STUDIO)", upper)
    return match.group(1) if match else None


def _match_room(room: str | None, basis: dict) -> str | None:
    if not room:
        return None
    names = [r["name"] for r in basis.get("rooms", [])]
    names += [t["scope"] for t in basis.get("design_totals", [])]
    for name in names:
        if room.upper() in name.upper() or name.upper() in room.upper():
            return name
    return room


def answer_plan_question(text: str, basis: dict) -> dict:
    """Grounded blueprint Q&A: every answer cites sheet/page/provenance."""
    upper = text.upper()
    instances = {d["device_id"]: d for d in basis.get("instances", [])}
    equipment = {e["tag"]: e for e in basis.get("equipment", [])}
    supply_totals = [
        t for t in basis.get("design_totals", []) if t["function"] == "SUPPLY"
    ]

    tag_match = re.search(
        r"\b(SA|SD|RA|EA|EF|EG|RG|RF|SF|RTU|AHU|FCU|VAV|LI|CR|OA)-?\s?\d{1,3}\b",
        upper,
    )
    if tag_match:
        tag = tag_match.group(0).upper().replace(" ", "-")
        tag = re.sub(r"-(\s*)(\d+)$", r"-\2", tag)
        if tag in instances:
            d = instances[tag]
            return {
                "answer": (
                    f"{tag} is a {d.get('type') or 'air device'} in "
                    f"{d.get('room') or 'unassigned room'}; design "
                    f"{d.get('design_cfm')} CFM, size {d.get('size') or 'n/a'}. "
                    f"Source: {d['source'].get('sheet') or '?'} "
                    f"(page {d['source'].get('page')}, "
                    f"{d['source'].get('extraction_method')})."
                ),
                "source": d["source"], "device": tag,
            }
        if tag in equipment:
            e = equipment[tag]
            return {
                "answer": (
                    f"{tag} is a {e.get('type') or 'unit'} "
                    f"({e.get('manufacturer')} {e.get('model')}); "
                    f"supply {e.get('supply_cfm')} CFM. "
                    f"Source: {e['source'].get('sheet') or '?'} "
                    f"(page {e['source'].get('page')})."
                ),
                "source": e["source"], "equipment": tag,
            }
        return {"answer": f"{tag} not found in the plan index.", "source": None}

    room = _match_room(_room_from_question(upper), basis)
    if ("TOTAL" in upper or "DESIGN SUPPLY" in upper) and room:
        match = next(
            (t for t in supply_totals
             if t["scope"].upper() == room.upper()),
            None,
        )
        if match:
            return {
                "answer": (
                    f"Design supply for {match['scope']} is "
                    f"{match['design_total_cfm']:.0f} CFM across "
                    f"{match['device_count']} devices. "
                    f"Source: {', '.join(match.get('source_sheets', [])) or 'plans'}."
                ),
                "source": {"sheet": ",".join(match.get("source_sheets", []) or [])},
            }
    if ("HOW MANY" in upper or "COUNT" in upper) and room:
        room_devices = [d for d in basis.get("instances", [])
                        if (d.get("room") or "").upper() == room.upper()]
        supply = [d for d in room_devices if d["device_id"].startswith("SA")]
        return {
            "answer": (
                f"{room} has {len(supply)} supply outlet(s) and "
                f"{len(room_devices) - len(supply)} return/exhaust device(s). "
                f"Source: plan sheets "
                f"{', '.join(sorted({d['source'].get('sheet') for d in room_devices if d['source'].get('sheet')})) or '?'}."
            ),
            "source": {"sheet": "plans"},
        }
    if "SCHEDULE" in upper and ("AIR DEVICE" in upper or "WHAT SHEET" in upper):
        page = next(
            (p for p in basis.get("sheet_classification", [])
             if p["type"] == "AIR_DEVICE_SCHEDULE"),
            None,
        )
        if page:
            return {
                "answer": (
                    f"The air device schedule is on sheet {page['sheet_number']} "
                    f"(page {page['page']})."
                ),
                "source": {"sheet": page["sheet_number"], "page": page["page"]},
            }
    if "SYSTEM SERVES" in upper or "WHAT SYSTEM" in upper:
        if room:
            device = next(
                (d for d in basis.get("instances", [])
                 if (d.get("room") or "").upper() == room.upper()),
                None,
            )
            if device:
                return {
                    "answer": (
                        f"{room} is served by the duct branch shown on "
                        f"{device['source'].get('sheet')} (page "
                        f"{device['source'].get('page')}); the serving unit is "
                        f"in the equipment schedule (M2.2)."
                    ),
                    "source": {"sheet": device["source"].get("sheet")},
                }
    # fallback: summary
    sheets = basis.get("sheet_classification", [])
    return {
        "answer": (
            "I can answer from the plan index. Found "
            f"{len(instances)} devices, {len(equipment)} equipment units, and "
            f"{len(supply_totals)} supply systems across "
            f"{len(sheets)} sheets."
        ),
        "source": None,
    }


class CopilotServer(BaseHTTPRequestHandler):
    paths: ReportPaths
    store: JobStore
    masters: MasterStore
    composer: Composer

    @classmethod
    def configure(cls, workspace: Path, masters_dir: Path) -> None:
        cls.paths = ReportPaths(workspace).ensure()
        cls.masters = MasterStore(cls.paths)
        try:
            cls.masters.install_masters(masters_dir)
        except FileNotFoundError as error:
            print(f"[copilot] WARN {error}", file=sys.stderr)
        cls.store = JobStore(cls.paths)
        cls.composer = Composer(cls.paths, cls.store)

    # ------------------------------------------------------------- helpers

    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _load(self, job_id: str) -> JobRecord:
        return self.store.load(job_id)

    def _save(self, record: JobRecord) -> JobRecord:
        return self.store.save(record)

    def _docs_file(self, job_id: str) -> Path:
        return self.paths.job_dir(job_id) / "documents.json"

    def _load_docs(self, job_id: str) -> list[dict]:
        path = self._docs_file(job_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return []

    def _save_docs(self, job_id: str, docs: list[dict]) -> None:
        self._docs_file(job_id).write_text(
            json.dumps(docs, indent=2, default=str), encoding="utf-8")

    def _basis_file(self, job_id: str) -> Path:
        return self.paths.job_dir(job_id) / "plan_basis.json"

    def _load_basis(self, job_id: str) -> dict | None:
        path = self._basis_file(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None

    def _save_basis(self, job_id: str, basis: dict) -> None:
        self._basis_file(job_id).write_text(
            json.dumps(basis, indent=2, default=str), encoding="utf-8")

    def _job_payload(self, record: JobRecord) -> dict:
        plan = plan_for(record)
        return {
            "job": record.to_dict(),
            "plan": plan.to_dict(),
            "completeness": evaluate(record).to_dict(),
            "ready_to_leave": ready_to_leave(record),
        }

    # ---------------------------------------------------------------- routing

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ("/", "/index.html"):
            self._send_ui()
        elif path == "/api/state":
            jobs = []
            for job_id in self.store.list_jobs():
                try:
                    record = self._load(job_id)
                except Exception:
                    continue
                jobs.append({
                    "job_id": job_id,
                    "project_name": record.metadata.project_name,
                    "site_name": record.metadata.site_name,
                    "report_type": record.metadata.report_type,
                    "test_date": (
                        record.metadata.test_date.isoformat()
                        if record.metadata.test_date else None
                    ),
                    "device_count": len(record.air_devices),
                    "photo_count": len(record.photos),
                })
            unchanged, _ = self.masters.verify_unchanged()
            self._send_json({"jobs": jobs, "masters_verified": unchanged,
                             "workspace": str(self.paths.root),
                             "document_vision": document_reader_status(
                                 build_document_reader())})
        elif path.startswith("/api/jobs/"):
            parts = path[len("/api/jobs/"):].split("/")
            if len(parts) == 2 and parts[1] == "download":
                self._download(parts[0])
            elif len(parts) == 2 and parts[1] == "preview":
                self._action_preview(parts[0])
            elif len(parts) == 3 and parts[1] == "photo":
                self._serve_photo(parts[0], parts[2])
            elif len(parts) == 1:
                self._job_detail(parts[0])
            else:
                self._send_json({"error": "not found"}, 404)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/jobs":
            self._create_job()
        elif path.startswith("/api/jobs/"):
            parts = path[len("/api/jobs/"):].split("/")
            if len(parts) == 2:
                action = parts[1]
                handler = getattr(self, "_action_" + action.replace("-", "_"), None)
                if handler is not None:
                    handler(parts[0])
                else:
                    self._send_json({"error": f"unknown action {action}"}, 400)
            else:
                self._send_json({"error": "not found"}, 404)
        else:
            self._send_json({"error": "not found"}, 404)

    # ------------------------------------------------------------- handlers

    def _create_job(self):
        body = self._read_body()
        project = (body.get("project_name") or "").strip()
        if not project:
            self._send_json({"error": "project_name required"}, 400)
            return
        job_id = body.get("job_id") or datetime.now().strftime("%Y%m%d%H%M%S")
        metadata = JobMetadata(
            job_id=job_id,
            project_name=project,
            project_number=body.get("project_number"),
            site_name=body.get("site_name") or "",
            test_date=(
                date.fromisoformat(body["test_date"])
                if body.get("test_date") else date.today()
            ),
            technician=body.get("technician") or "",
            hiring_contractor=body.get("hiring_contractor"),
            report_type=(body.get("report_type") or "TAB").upper(),
        )
        if "scope" in body and body["scope"]:
            metadata.report_type, scope_notes = detect_scope(body["scope"])
        record = JobRecord(metadata=metadata)
        if "scope" in body and body["scope"]:
            _, record.scope_notes = detect_scope(body["scope"])
        try:
            self.store.create(record)
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
            return
        self._send_json(self._job_payload(record))

    def _job_detail(self, job_id: str):
        try:
            record = self._load(job_id)
        except FileNotFoundError as error:
            self._send_json({"error": str(error)}, 404)
            return
        self._send_json(self._job_payload(record))

    def _action_chat(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        text = (body.get("text") or "").strip()
        if not text:
            self._send_json({"error": "text required"}, 400)
            return
        low = text.lower()
        if any(w in low for w in SCOPE_MARKERS) and not any(
            w in low for w in ("cfm", "fpm", "as found", "final", "reading")
        ):
            record.metadata.report_type, record.scope_notes = detect_scope(text)
        captures = parse_measurements(text)
        merged = 0
        for capture in captures:
            if merge_capture(record, capture):
                merged += 1
        self._save(record)
        self._send_json({
            "captures": [c.to_dict() for c in captures],
            "merged": merged,
            "scope_notes": record.scope_notes,
            "report_type": record.metadata.report_type,
            "payload": self._job_payload(record),
        })

    def _action_photos(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        sources = [Path(p) for p in (body.get("photo_paths") or [])]
        if not sources:
            self._send_json({"error": "photo_paths required"}, 400)
            return
        ingest = PhotoIngest(self.paths)
        entries = ingest.ingest(job_id, sources)
        record.photos.extend(entries)
        self._save(record)
        self._send_json({
            "photos": [p.to_dict() for p in entries],
            "payload": self._job_payload(record),
        })

    def _action_measurements(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        text = (body.get("text") or "").strip()
        captures = parse_measurements(text)
        merged = 0
        for capture in captures:
            if merge_capture(record, capture):
                merged += 1
        self._save(record)
        self._send_json({"captures": [c.to_dict() for c in captures],
                         "merged": merged,
                         "payload": self._job_payload(record)})

    def _action_devices(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        device_id = (body.get("device_id") or "").strip()
        if not device_id:
            self._send_json({"error": "device_id required"}, 400)
            return
        device = next(
            (d for d in record.air_devices if d.device_id == device_id), None
        )
        if device is None:
            device = AirDevice(device_id=device_id,
                               function=body.get("function") or "SUPPLY",
                               measurement_method="rotating vane")
            record.air_devices.append(device)
        for key in ("area_served", "function", "measurement_method", "size",
                    "status", "notes"):
            if body.get(key) is not None:
                setattr(device, key, body[key])
        for key in ("design_cfm", "as_found_cfm", "final_cfm", "avg_velocity_fpm"):
            if body.get(key) is not None:
                try:
                    setattr(device, key, float(body[key]))
                except (TypeError, ValueError):
                    pass
        self._save(record)
        self._send_json(self._job_payload(record))

    def _action_equipment(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        equipment_id = (body.get("equipment_id") or "").strip()
        if not equipment_id:
            self._send_json({"error": "equipment_id required"}, 400)
            return
        equipment = Equipment(
            equipment_id=equipment_id,
            equipment_type=EquipmentType(body.get("equipment_type") or "OTHER"),
            tag=body.get("tag") or equipment_id,
            manufacturer=body.get("manufacturer"),
            model=body.get("model"),
            serial=body.get("serial"),
            area_served=body.get("area_served"),
        )
        record.equipment.append(equipment)
        self._save(record)
        self._send_json(self._job_payload(record))

    def _action_findings(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        title = (body.get("title") or "").strip()
        if not title:
            self._send_json({"error": "title required"}, 400)
            return
        record.findings.append(Finding(
            title=title,
            detail=body.get("detail") or "",
            category=body.get("category") or "observation",
            severity=body.get("severity") or "minor",
        ))
        self._save(record)
        self._send_json(self._job_payload(record))

    def _action_completeness(self, job_id: str):
        record = self._load(job_id)
        self._send_json(ready_to_leave(record))

    def _action_plan(self, job_id: str):
        record = self._load(job_id)
        self._send_json(plan_for(record).to_dict())

    def _action_docs(self, job_id: str):
        record = self._load(job_id)
        body = self._read_body()
        sources = [Path(p) for p in (body.get("document_paths") or [])]
        if not sources:
            self._send_json({"error": "document_paths required"}, 400)
            return
        docs = self._load_docs(job_id)
        docs_dir = self.paths.job_subdir(job_id, "docs")
        created = []
        for source in sources:
            if not source.exists():
                continue
            digest = sha256_of(source)
            if any(d.get("sha256") == digest for d in docs):
                continue
            target = docs_dir / source.name
            if not target.exists():
                import shutil
                shutil.copy2(source, target)
            indexed = index_pdf(target)
            entry = {
                "document_id": f"DOC-{digest[:8]}",
                "filename": target.name,
                "sha256": digest,
                "page_count": len(indexed.pages),
                "revision": None,
                "uploaded_at": datetime.now().isoformat(timespec="seconds"),
                "path": str(target),
            }
            docs.append(entry)
            created.append(entry)
        self._save_docs(job_id, docs)
        self._send_json({"documents": docs, "created": created})

    def _action_prepare(self, job_id: str):
        record = self._load(job_id)
        docs = self._load_docs(job_id)
        if not docs:
            self._send_json({"error": "upload plans first"}, 400)
            return
        reader = build_document_reader()
        merged = None
        for doc in docs:
            basis = cached_blueprint(
                Path(doc["path"]),
                self.paths.job_dir(job_id) / "plan_cache",
                reader,
            )
            basis = {k: v for k, v in basis.items() if k != "_cache_hit"}
            if merged is None:
                merged = basis
            else:
                from scs_reports.blueprint_raster import merge_basis
                merged = merge_basis(merged, basis)
        # re-apply any known owner corrections for this document hash
        corrections_path = self.paths.job_dir(job_id) / "corrections.json"
        for device in merged.get("instances", []):
            known = apply_known_correction(
                corrections_path,
                merged["document"].get("sha256", ""),
                device["device_id"],
                device["source"].get("sheet"),
            )
            if known is not None:
                device["corrected_value"] = known
        self._save_basis(job_id, merged)
        # build the MechanicalPlanGraph (native words + OCR words for sparse pages)
        graph = self._build_plan_graph(job_id, docs, reader)
        self._graph_file(job_id).write_text(
            json.dumps(graph.to_dict(), indent=2, default=str), encoding="utf-8")
        build_preengineered_record(record, merged)
        self._save(record)
        preview = self._plan_preview(merged)
        self._send_json({
            "preview": preview,
            "design_totals": merged["design_totals"],
            "conflicts": merged["conflicts"],
            "system_associations": merged.get("system_associations", []),
            "devices": len(merged["instances"]),
            "rooms": merged["rooms"],
            "sheets": merged["sheet_classification"],
            "field_plan": field_plan(graph, record.scope_notes or "verify airflow"),
            "graph": {
                "schema_version": graph.schema_version,
                "equipment": len(graph.equipment),
                "air_devices": len(graph.air_devices),
                "dampers": len(graph.dampers),
                "controls": len(graph.controls),
                "duct_segments": len(graph.duct_segments),
                "rooms": len(graph.rooms),
                "notes": len(graph.notes),
                "references": len(graph.references),
                "schedules": len(graph.schedules),
                "relationships": len(graph.relationships),
                "missing_context": graph.missing_context,
                "validation_issues": graph.validate(),
            },
            "payload": self._job_payload(record),
        })

    def _graph_file(self, job_id: str) -> Path:
        return self.paths.job_dir(job_id) / "plan_graph.json"

    def _load_graph(self, job_id: str):
        path = self._graph_file(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _build_plan_graph(self, job_id: str, docs: list[dict], reader):
        from scs_reports.plan_graph import MechanicalPlanGraph
        from scs_reports.plan_packet import PlanPacket

        native_docs = []
        raster_words: dict[int, list] = {}
        cache_dir = self.paths.job_dir(job_id) / "plan_cache"
        for doc in docs:
            native = index_pdf(Path(doc["path"]), tables=False)
            native_docs.append(native)
            for page in native.pages:
                if not page.words:
                    words, _orientation = _ocr_with_orientation(
                        Path(doc["path"]), page.page_number, reader, 200,
                        cache_dir, doc["sha256"])
                    raster_words[page.page_number] = words
        graph = build_graph(native_docs, raster_words=raster_words)
        return graph

    def _action_correct(self, job_id: str):
        body = self._read_body()
        device = (body.get("device") or "").strip()
        if not device or body.get("corrected") is None:
            self._send_json({"error": "device + corrected required"}, 400)
            return
        basis = self._load_basis(job_id)
        sha = (basis or {}).get("document", {}).get("sha256", "")
        original = body.get("original")
        sheet = body.get("sheet")
        corrections_path = self.paths.job_dir(job_id) / "corrections.json"
        save_correction(
            corrections_path,
            sha256=sha,
            device=device,
            original_value=original,
            corrected_value=body["corrected"],
            sheet=sheet,
            page=body.get("page"),
            bbox=body.get("bbox"),
            extraction_method=body.get("extraction_method"),
            corrected_by=body.get("corrected_by") or "owner",
            reason=body.get("reason"),
        )
        self._send_json({
            "ok": True,
            "correction": load_corrections(corrections_path).get(
                f"{sha[:12]}::{sheet or '?'}::{device}"
            ),
            "note": "original extraction preserved; correction recorded",
        })

    @staticmethod
    def _plan_preview(basis: dict) -> dict:
        rooms = []
        for total in basis.get("design_totals", []):
            if total["function"] == "SUPPLY":
                rooms.append({
                    "room": total["scope"],
                    "supply_devices": total["device_count"],
                    "design_supply_cfm": total["design_total_cfm"],
                    "source_sheets": total.get("source_sheets", []),
                })
        mechanical_sheets = [
            {
                "page": s["page"], "sheet": s["sheet_number"], "title": s["title"],
                "type": s["type"], "confidence": s["confidence"],
            }
            for s in basis.get("sheet_classification", [])
            if s["type"] not in ("ELECTRICAL", "ARCHITECTURAL", "PLUMBING",
                                 "COVER", "IRRELEVANT")
        ]
        return {
            "rooms": rooms,
            "relevant_sheets": mechanical_sheets,
            "conflicts": basis.get("conflicts", []),
        }

    def _action_plan_chat(self, job_id: str):
        body = self._read_body()
        text = (body.get("text") or "").strip()
        graph_payload = self._load_graph(job_id)
        if graph_payload is not None:
            from scs_reports.plan_graph import MechanicalPlanGraph
            graph = MechanicalPlanGraph(packet={})
            for key, value in graph_payload.items():
                if key in ("packet",):
                    continue
                if key == "relationships":
                    from scs_reports.plan_graph import Relationship
                    graph.relationships = [
                        Relationship(r["source"], r["target"], r["rel_type"],
                                     r.get("evidence", []), r.get("confidence", "HIGH"),
                                     r.get("source_ref"))
                        for r in value
                    ]
                else:
                    setattr(graph, key, value)
            answer = answer_graph_question(text, graph)
            self._send_json(answer)
            return
        basis = self._load_basis(job_id)
        if not basis:
            self._send_json({"error": "prepare from plans first"}, 400)
            return
        answer = answer_plan_question(text, basis)
        self._send_json(answer)

    def _action_preview(self, job_id: str):
        query = urlparse(self.path).query
        params = {k: v[0] for k, v in parse_qs(query).items()}
        page_no = int(params.get("page", 1))
        bbox = [float(x) for x in params.get("bbox", "0,0,0,0").split(",")]
        docs = self._load_docs(job_id)
        if not docs:
            self._send_json({"error": "no documents"}, 404)
            return
        if fitz is None:
            self._send_json({"error": "renderer unavailable"}, 500)
            return
        try:
            renderer = fitz.open(docs[0]["path"])
            page = renderer.load_page(page_no - 1)
            zoom = 3.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                  clip=fitz.Rect(*bbox))
            png = pix.tobytes("png")
            renderer.close()
        except Exception as error:
            self._send_json({"error": f"render failed: {error}"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def _action_copilot(self, job_id: str):
        """SCS Copilot: one job-aware question -> tool-routed sourced answer."""
        record = self._load(job_id)
        body = self._read_body()
        question = (body.get("question") or "").strip()
        if not question:
            self._send_json({"error": "question required"}, 400)
            return
        from scs_copilot.context import SCSJobContext
        from scs_copilot.router import CopilotRouter
        from scs_knowledge.registry import SCSKnowledgeLibrary
        from scs_knowledge.gaps_lessons import KnowledgeGapLog
        from scs_reports.plan_graph import MechanicalPlanGraph

        graph = None
        graph_payload = self._load_graph(job_id)
        if graph_payload is not None:
            graph = MechanicalPlanGraph(packet={})
            for key, value in graph_payload.items():
                if key == "relationships":
                    from scs_reports.plan_graph import Relationship
                    graph.relationships = [
                        Relationship(r["source"], r["target"], r["rel_type"],
                                     r.get("evidence", []), r.get("confidence", "HIGH"),
                                     r.get("source_ref")) for r in value]
                elif key != "packet":
                    setattr(graph, key, value)
        basis = self._load_basis(job_id) or {}
        context = SCSJobContext(job_id=job_id, job=record, graph=graph,
                                design_basis=basis)
        for device in record.air_devices:
            if device.final_cfm is not None:
                context.record_reading(f"{device.device_id}:final_cfm",
                                       device.final_cfm)
        knowledge_dir = self.paths.root / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        library = SCSKnowledgeLibrary(knowledge_dir / "library.db")
        gaps = KnowledgeGapLog(knowledge_dir / "gaps.json")
        router = CopilotRouter(context=context, knowledge=library, gaps=gaps)
        answer = router.route(question)
        library.close()
        self._send_json({"question": question, **answer})

    def _action_calculate(self, job_id: str):
        body = self._read_body()
        name = (body.get("calculator") or "").strip()
        inputs = body.get("inputs") or {}
        from scs_engineering.calculators import run_calculator
        self._send_json({"calculation": run_calculator(name, **inputs)})

    def _action_generate(self, job_id: str):
        record = self._load(job_id)
        plan = plan_for(record)
        try:
            output = self.composer.compose(record, plan)
        except Exception as error:
            self._send_json({"error": f"compose failed: {type(error).__name__}: {error}"}, 500)
            return
        validation = validate_report(record, plan, output,
                                     masters=self.masters)
        self._send_json({
            "output": str(output),
            "output_name": output.name,
            "validation": {
                "summary": validation.summary(),
                "checks": [
                    {"name": c.name, "status": c.status, "message": c.message}
                    for c in validation.checks
                ],
            },
        })

    def _download(self, job_id: str):
        record = self._load(job_id)
        from scs_reports.composer import output_stem
        stem = output_stem(record)
        output_dir = self.paths.output_dir(job_id)
        candidates = sorted(
            (p for p in output_dir.glob(f"{stem}*.xlsx") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            self._send_json({"error": "no generated report yet"}, 404)
            return
        target = candidates[-1]
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_photo(self, job_id: str, photo_id: str):
        record = self._load(job_id)
        photo = next((p for p in record.photos if p.photo_id == photo_id), None)
        if photo is None:
            self._send_json({"error": "no such photo"}, 404)
            return
        source = self.paths.job_subdir(job_id, "originals") / photo.original_filename
        if not source.exists():
            self._send_json({"error": "photo file missing"}, 404)
            return
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = source.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_ui(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        body = INDEX_HTML.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quiet
        pass


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><title>SCS Job Copilot</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.45 system-ui, Segoe UI, sans-serif; background:#12141a; color:#e6e8ee; }
header { display:flex; align-items:center; gap:14px; padding:10px 16px; background:#1a1d26; border-bottom:1px solid #2a2f3a; position:sticky; top:0; z-index:5; flex-wrap:wrap; }
header h1 { font-size:15px; margin:0; font-weight:600; }
header .spacer { flex:1; }
main { display:grid; grid-template-columns: minmax(0,1fr) minmax(340px,1fr); gap:0; height:calc(100vh - 52px); }
#left { padding:12px 16px; overflow-y:auto; }
#right { padding:12px 16px; overflow-y:auto; border-left:1px solid #2a2f3a; background:#161a22; }
button, select, input, textarea { font:inherit; color:inherit; }
button { background:#232834; border:1px solid #3a4150; border-radius:6px; padding:6px 12px; cursor:pointer; }
button:hover { background:#2c3342; }
button.primary { background:#2563eb; border-color:#2563eb; color:#fff; }
button.green { background:#1e5e34; border-color:#2f8a4c; color:#d7f2df; }
select { background:#232834; border:1px solid #3a4150; border-radius:6px; padding:6px 8px; }
input, textarea { background:#171a21; border:1px solid #3a4150; border-radius:6px; padding:6px 8px; width:100%; }
label { display:block; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#8b93a5; margin:10px 0 4px; }
h2 { font-size:13px; color:#9aa4b5; text-transform:uppercase; letter-spacing:.08em; margin:16px 0 6px; }
.card { background:#1a1e28; border:1px solid #2a2f3a; border-radius:8px; padding:10px 12px; margin:8px 0; }
pre { white-space:pre-wrap; color:#b9c2d4; font-size:12px; margin:4px 0; }
.badge { display:inline-block; border-radius:4px; padding:1px 8px; font-size:11px; margin-right:6px; }
.badge.ready { background:#16381f; color:#a7e8bb; border:1px solid #2f8a4c; }
.badge.missing { background:#3a1616; color:#f0b3b3; border:1px solid #c0392b; }
.badge.ok { background:#1e2c3a; color:#9db8e8; border:1px solid #2c3d5c; }
#msg { position:fixed; bottom:14px; right:14px; background:#173a24; border:1px solid #2f6b44; color:#b8e6c8; padding:8px 14px; border-radius:8px; opacity:0; transition:opacity .25s; z-index:10; }
#msg.err { background:#3a1a1a; border-color:#6b2f2f; color:#e6b8b8; }
.row { display:grid; grid-template-columns:1fr 1fr; gap:0 12px; }
</style></head>
<body>
<header>
  <h1>SCS Job Copilot</h1>
  <select id="jobSel" onchange="loadJob(this.value)"><option value="">-- select / create job --</option></select>
  <div class="spacer"></div>
  <span id="masters"></span>
  <button onclick="refreshState()">Refresh</button>
</header>
<main>
<div id="left">
  <h2>JOB</h2>
  <div class="card">
    <div class="row">
      <div><label>Project / Client</label><input id="project_name" placeholder="Workout Studio Airflow Verification"></div>
      <div><label>Site</label><input id="site_name" placeholder="Studio A & B"></div>
    </div>
    <div class="row">
      <div><label>Job #</label><input id="project_number" placeholder="A-1234"></div>
      <div><label>Test date</label><input id="test_date" type="date"></div>
    </div>
    <div class="row">
      <div><label>Technician</label><input id="technician" placeholder="Aaron T."></div>
      <div><label>Report type</label>
        <select id="report_type"><option>TAB</option><option selected>AIRFLOW_VERIFICATION</option></select>
      </div>
    </div>
    <label>Scope (natural language)</label>
    <textarea id="scope" rows="2" placeholder="Airflow verification and slight balancing of two newly installed ductwork systems serving small workout studio areas."></textarea>
    <button class="primary" onclick="createJob()" style="margin-top:8px">Create job</button>
  </div>

  <h2>CHAT</h2>
  <div class="card">
    <textarea id="chat" rows="3" placeholder="'Scope: airflow verification of two duct systems. Studio A SA-3 was 142 CFM as found; I opened the damper and got 181 final.'"></textarea>
    <button class="green" onclick="sendChat()" style="margin-top:8px">Send (scope + measurements)</button>
    <div id="chatOut"></div>
  </div>

  <h2>PHOTOS</h2>
  <div class="card">
    <label>Absolute paths (one per line)</label>
    <textarea id="photoPaths" rows="3" placeholder="C:\\path\\to\\photo1.jpg&#10;C:\\path\\to\\photo2.HEIC"></textarea>
    <button class="green" onclick="ingestPhotos()" style="margin-top:8px">Ingest photos</button>
    <div id="photoOut"></div>
  </div>

  <h2>BLUEPRINT PLANS</h2>
  <div class="card">
    <label>PDF paths (one per line) - upload as job artifact (immutable)</label>
    <textarea id="docPaths" rows="2" placeholder="C:\\path\\to\\mechanical_prints.pdf"></textarea>
    <button class="green" onclick="uploadDocs()" style="margin-top:8px">Upload plans</button>
    <button class="primary" onclick="prepareFromPlans()" style="margin-top:8px">Prepare from plans</button>
    <div id="planOut"></div>
  </div>

  <h2>PLAN CHAT</h2>
  <div class="card">
    <textarea id="planChat" rows="2" placeholder="What is SA-6 supposed to be? How many supply diffusers are in Studio B? What is the design total for Studio A?"></textarea>
    <button onclick="askPlan()" style="margin-top:8px">Ask about the plans</button>
    <div id="planChatOut"></div>
  </div>

  <h2>MEASUREMENTS</h2>
  <div class="card">
    <textarea id="meas" rows="3" placeholder="Studio B SA-1 was 300 CFM as found. Balanced damper, got 418 final."></textarea>
    <button onclick="sendMeasurements()" style="margin-top:8px">Capture measurements</button>
    <div id="measOut"></div>
  </div>

  <h2>FINDINGS</h2>
  <div class="card">
    <div class="row">
      <div><label>Title</label><input id="find_title" placeholder="Loose flex connection"></div>
      <div><label>Severity</label><select id="find_sev"><option>minor</option><option>major</option><option>critical</option></select></div>
    </div>
    <label>Detail</label>
    <input id="find_detail" placeholder="Flex strap loose at Studio A plenum">
    <button onclick="addFinding()" style="margin-top:8px">Add finding</button>
  </div>

  <h2>REPORT PLAN & GENERATE</h2>
  <div class="card">
    <div id="planOut"></div>
    <button class="primary" onclick="generate()">Generate report</button>
    <button class="green" id="dlBtn" style="display:none" onclick="download()">Download workbook</button>
    <div id="genOut"></div>
  </div>
</div>

<div id="right">
  <h2>READY TO LEAVE?</h2>
  <div id="readyBox" class="card"><span class="badge ok">no job loaded</span></div>
  <h2>DEVICES</h2>
  <div id="devicesBox" class="card"></div>
  <h2>JOB RECORD</h2>
  <pre id="recordOut"></pre>
</div>
</main>
<div id="msg"></div>
<script>
let current = null;
let lastPlan = [];
async function api(url, method, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok && !j.error) j.error = "HTTP " + r.status;
  return j;
}
function msg(text, err) { const el = document.getElementById("msg"); el.textContent = text; el.className = err ? "err" : ""; el.style.opacity = 1; clearTimeout(msg._t); msg._t = setTimeout(() => el.style.opacity = 0, 2500); }
async function refreshState() {
  const s = await api("/api/state", "GET");
  document.getElementById("masters").textContent = s.masters_verified ? "masters verified" : "MASTERS UNVERIFIED";
  const sel = document.getElementById("jobSel");
  const prev = sel.value;
  sel.innerHTML = '<option value="">-- select / create job --</option>' + s.jobs.map(j =>
    `<option value="${j.job_id}">${j.project_name} (${j.site_name}) [${j.report_type}] ${j.device_count} devices, ${j.photo_count} photos</option>`).join("");
  sel.value = prev;
  if (prev && current === null) loadJob(prev);
}
async function createJob() {
  const body = {
    project_name: val("project_name"), site_name: val("site_name"),
    project_number: val("project_number"), test_date: val("test_date"),
    technician: val("technician"), report_type: val("report_type"),
    scope: val("scope"),
  };
  const j = await api("/api/jobs", "POST", body);
  if (j.error) { msg(j.error, true); return; }
  current = j.job.metadata.job_id;
  msg("Job created: " + current);
  await refreshState();
  await loadJob(current);
}
async function loadJob(id) {
  if (!id) { current = null; return; }
  current = id;
  const j = await api("/api/jobs/" + encodeURIComponent(id), "GET");
  if (j.error) { msg(j.error, true); return; }
  renderPayload(j);
}
function renderPayload(p) {
  lastPlan = p.plan.sections || [];
  document.getElementById("planOut").innerHTML = lastPlan.map(s => `<span class="badge ok">${s.type}</span>`).join("") || "no plan";
  document.getElementById("recordOut").textContent = JSON.stringify(p.job, null, 1);
  renderReady(p.ready_to_leave);
  renderDevices(p.job.air_devices || []);
  document.getElementById("dlBtn").style.display = "none";
}
function renderReady(r) {
  const box = document.getElementById("readyBox");
  const lines = [];
  lines.push(`<span class="badge ${r.ready ? "ready" : "missing"}">${r.readiness}</span>`);
  if (r.MISSING_BEFORE_LEAVING && r.MISSING_BEFORE_LEAVING.length)
    lines.push("<b>MISSING BEFORE LEAVING</b><pre>" + r.MISSING_BEFORE_LEAVING.join("&#10;") + "</pre>");
  if (r.OPTIONAL && r.OPTIONAL.length)
    lines.push("<b>OPTIONAL</b><pre>" + r.OPTIONAL.join("&#10;") + "</pre>");
  if (r.questions && r.questions.length)
    lines.push("<b>QUESTIONS</b><pre>" + r.questions.join("&#10;") + "</pre>");
  box.innerHTML = lines.join("");
}
function renderDevices(devices) {
  const rows = devices.map(d =>
    `<div style="padding:3px 0;border-bottom:1px dashed #232936"><b>${d.device_id}</b> ${d.function} ${d.area_served || ""} | design ${d.design_cfm ?? "-"} | as-found ${d.as_found_cfm ?? "-"} | final ${d.final_cfm ?? "-"} CFM | ${d.measurement_method || ""} | ${d.status || ""}</div>`).join("");
  document.getElementById("devicesBox").innerHTML = rows || "no devices yet";
}
async function sendChat() {
  const text = val("chat");
  if (!text || !current) return msg("load/create a job first", true);
  const j = await api("/api/jobs/" + current + "/chat", "POST", { text });
  if (j.error) return msg(j.error, true);
  document.getElementById("chatOut").innerHTML = "<pre>" + JSON.stringify(j.captures || [], null, 1) + "</pre>";
  msg("Chat processed; merged " + (j.merged || 0) + " measurement(s)");
  renderPayload(j.payload);
}
async function ingestPhotos() {
  const paths = val("photoPaths").split("\\n").map(s => s.trim()).filter(Boolean);
  if (!paths.length || !current) return msg("provide paths + job", true);
  const j = await api("/api/jobs/" + current + "/photos", "POST", { photo_paths: paths });
  if (j.error) return msg(j.error, true);
  document.getElementById("photoOut").innerHTML = "<pre>" + JSON.stringify(j.photos || [], null, 1) + "</pre>";
  msg("Ingested " + (j.photos || []).length + " photo(s)");
  renderPayload(j.payload);
}
async function uploadDocs() {
  const paths = val("docPaths").split("\\n").map(s => s.trim()).filter(Boolean);
  if (!paths.length || !current) return msg("provide PDF paths + job", true);
  const j = await api("/api/jobs/" + current + "/docs", "POST", { document_paths: paths });
  if (j.error) return msg(j.error, true);
  document.getElementById("planOut").innerHTML = "<pre>" + JSON.stringify(j.documents || [], null, 1) + "</pre>";
  msg("Uploaded " + (j.created || []).length + " plan document(s)");
}
async function prepareFromPlans() {
  if (!current) return msg("load/create a job first", true);
  msg("Reading the prints...", false);
  const j = await api("/api/jobs/" + current + "/prepare", "POST", {});
  if (j.error) return msg(j.error, true);
  const p = j.preview || {};
  const lines = ["<b>SYSTEMS / ROOMS FOUND</b>"];
  (p.rooms || []).forEach(r => lines.push(`${r.room}: ${r.supply_devices} supply devices, design supply ${r.design_supply_cfm} CFM`));
  lines.push("<b>RELEVANT SHEETS</b>");
  (p.relevant_sheets || []).forEach(s => lines.push(`${s.sheet} ${s.type} (conf ${s.confidence})`));
  if (j.conflicts && j.conflicts.length) { lines.push("<b>DOCUMENT CONFLICTS</b>"); j.conflicts.forEach(c => lines.push(c.detail)); }
  lines.push("<b>FIELD PLAN</b>");
  (j.field_plan || []).slice(0, 6).forEach(d => lines.push(`${d.device} ${d.room || ""} design ${d.design_cfm} ${d.size || ""} [${d.status}]`));
  document.getElementById("planOut").innerHTML = "<pre>" + lines.join("&#10;") + "</pre>";
  msg("Pre-engineered " + j.devices + " devices from plans; job status PRE_ENGINEERED");
  renderPayload(j.payload);
}
async function askPlan() {
  const text = val("planChat");
  if (!text || !current) return msg("enter a question", true);
  const j = await api("/api/jobs/" + current + "/plan-chat", "POST", { text });
  if (j.error) return msg(j.error, true);
  document.getElementById("planChatOut").innerHTML =
    "<pre>" + (j.answer || "") + "</pre>" +
    (j.source ? `<div class="hint">source: ${JSON.stringify(j.source)}</div>` : "");
}
async function sendMeasurements() {
  const text = val("meas");
  if (!text || !current) return msg("load/create a job first", true);
  const j = await api("/api/jobs/" + current + "/measurements", "POST", { text });
  if (j.error) return msg(j.error, true);
  document.getElementById("measOut").innerHTML = "<pre>" + JSON.stringify(j.captures || [], null, 1) + "</pre>";
  msg("Merged " + (j.merged || 0) + " measurement(s)");
  renderPayload(j.payload);
}
async function addFinding() {
  if (!current) return msg("load/create a job first", true);
  const j = await api("/api/jobs/" + current + "/findings", "POST",
    { title: val("find_title"), detail: val("find_detail"), severity: val("find_sev") });
  if (j.error) return msg(j.error, true);
  msg("Finding added");
  renderPayload(j);
}
async function generate() {
  if (!current) return msg("load/create a job first", true);
  const j = await api("/api/jobs/" + current + "/generate", "POST", {});
  if (j.error) return msg(j.error, true);
  const v = j.validation || {};
  document.getElementById("genOut").innerHTML = `<span class="badge ${v.blocked ? "missing" : "ready"}">${v.summary}</span><pre>${JSON.stringify(v.checks || [], null, 1)}</pre>`;
  document.getElementById("dlBtn").style.display = "inline-block";
  msg("Report generated: " + j.output_name);
}
function download() {
  if (!current) return;
  const a = document.createElement("a");
  a.href = "/api/jobs/" + encodeURIComponent(current) + "/download";
  a.download = "";
  document.body.appendChild(a); a.click(); a.remove();
}
function val(id) { return document.getElementById(id).value.trim(); }
refreshState();
</script>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3220)
    parser.add_argument("--workspace", default=r"C:\SCS_DATA\copilot")
    parser.add_argument("--masters", default=r"C:\SCS_DATA\masters")
    args = parser.parse_args()
    CopilotServer.configure(Path(args.workspace), Path(args.masters))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), CopilotServer)
    print(f"[copilot] serving at http://127.0.0.1:{args.port}")
    print(f"[copilot] workspace {args.workspace}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())