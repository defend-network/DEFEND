"""Local labeling server for the real-photo benchmark corpus (P2/P3).

Workflow: AI/OCR -> deterministic validation/correction -> PREPOPULATED
proposed ground truth -> owner reviews exceptions -> one-click CONFIRM.

Serves a single-page review UI on http://127.0.0.1:3210 so the owner can
confirm ground truth for the 49 real photos imported from Google Drive.
Labels are written atomically to real/labels.json (never into the live SCS
system). Only CONFIRMED labels count toward benchmark metrics.

Usage:
    python tools/vision_label_server.py [--port 3210] [--data C:/SCS_DATA/vision-benchmark/real]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from vision_autofill import attach_sequences, autopopulated_fields, reconcile

try:
    import vision_field_catalog as _CATALOG
except Exception:  # pragma: no cover
    _CATALOG = None

VALID_STATUSES = ("UNLABELED", "PARTIAL", "CONFIRMED", "NOT_USEFUL")
VALID_PHOTO_TYPES = tuple(_CATALOG.PHOTO_TYPE_SCHEMAS) if _CATALOG else (
    "NAMEPLATE",
    "INSTRUMENT_READING",
    "TEMP_RH_READING",
    "DUCTWORK",
    "EQUIPMENT",
    "SYSTEM_STATIC",
    "OTHER",
)
EDITABLE_FIELDS = ("photo_type", "manufacturer", "model", "serial",
                   "equipment_type", "equipment_tag", "readings",
                   "visible_text", "notes")


def load_json(path: Path, fallback):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return fallback


def _flat_fact(field_id: str, value, unit: str = "") -> dict:
    return {
        "value": value,
        "unit": unit,
        "source_class": "PHOTO_CONFIRMED",
        "confidence": 1.0,
        "extraction_method": "MANUAL",
        "corroboration": "SINGLE",
        "needs_confirmation": False,
        "expected_by_report": True,
        "destination_candidates": [],
        "rejected": False,
    }


def normalize_label(raw: dict) -> dict:
    """Coerce legacy/foreign label shapes into the structured schema."""
    readings = raw.get("readings")
    if not isinstance(readings, list):
        readings = []
    structured = []
    for r in readings:
        if isinstance(r, dict) and "reading_type" in r:
            structured.append(r)
        else:
            structured.append({
                "reading_type": "MANUAL",
                "value": str(r),
                "unit": "",
                "source_photo": None,
                "confidence": 1.0,
            })

    facts = raw.get("facts") or {}
    structured_facts: dict[str, dict] = {}
    if isinstance(facts, dict):
        items = facts.items()
    elif isinstance(facts, list):
        items = ((f.get("field_type") or f.get("field"), f) for f in facts)
    else:
        items = ()
    for fid, f in items:
        if not fid:
            continue
        if isinstance(f, str):
            f = {"value": f}
        if not isinstance(f, dict):
            continue
        structured_facts[str(fid)] = {
            "value": f.get("value"),
            "unit": f.get("unit") or "",
            "source_class": f.get("source_class") or "TECH_ENTERED",
            "confidence": float(f.get("confidence") or 1.0),
            "extraction_method": f.get("extraction_method") or "MANUAL",
            "corroboration": f.get("corroboration") or "SINGLE",
            "needs_confirmation": bool(f.get("needs_confirmation", False)),
            "expected_by_report": bool(f.get("expected_by_report", True)),
            "destination_candidates": list(f.get("destination_candidates") or []),
            "rejected": bool(f.get("rejected", False)),
        }
    if not structured_facts:
        for fid, val in (("photo_type", raw.get("photo_type")),
                         ("manufacturer", raw.get("manufacturer")),
                         ("model", raw.get("model")),
                         ("serial", raw.get("serial")),
                         ("equipment_type", raw.get("equipment_type")),
                         ("equipment_tag", raw.get("equipment_tag"))):
            if val:
                structured_facts[fid] = _flat_fact(fid, val)
        for r in structured:
            fid = str(r.get("reading_type", "MANUAL")).lower()
            structured_facts.setdefault(fid, _flat_fact(fid, r.get("value"), r.get("unit") or ""))
    if not structured_facts and raw.get("rejected_fields"):
        for fid in raw.get("rejected_fields") or []:
            structured_facts[str(fid)] = _flat_fact(str(fid), "", "")
            structured_facts[str(fid)]["rejected"] = True

    return {
        "photo_type": raw.get("photo_type"),
        "manufacturer": raw.get("manufacturer"),
        "model": raw.get("model"),
        "serial": raw.get("serial"),
        "equipment_type": raw.get("equipment_type"),
        "equipment_tag": raw.get("equipment_tag"),
        "readings": structured,
        "visible_text": raw.get("visible_text"),
        "notes": raw.get("notes"),
        "facts": structured_facts,
        "status": (raw.get("status") or "UNLABELED").upper(),
        "source": raw.get("source") or "MANUAL",
        "rejected_fields": list(raw.get("rejected_fields") or []),
    }


def _fact_source_class(cand: dict) -> str:
    """Map an extraction method to the SCS source-class taxonomy."""
    if cand.get("corroboration") == "OCR+VLM":
        return "PHOTO_CONFIRMED"
    if cand.get("extraction_method") == "OCR_REGEX":
        return "PHOTO_OCR"
    if cand.get("extraction_method") == "VLM_FACT":
        return "PHOTO_VLM"
    return "UNKNOWN"


def proposal_label(photo: dict) -> dict:
    """Build the CONFIRMED label from a SAFE proposal."""
    f = photo["proposal"]["fields"]
    facts: dict[str, dict] = {}
    for cand in photo["proposal"].get("facts") or []:
        fid = cand["field_type"]
        if not cand.get("value"):
            continue
        facts[fid] = {
            "value": cand["value"],
            "unit": cand.get("unit") or "",
            "source_class": _fact_source_class(cand),
            "confidence": cand.get("confidence") or 1.0,
            "extraction_method": cand.get("extraction_method") or "MANUAL",
            "corroboration": cand.get("corroboration") or "SINGLE",
            "needs_confirmation": bool(cand.get("needs_confirmation", False)),
            "expected_by_report": bool(cand.get("expected_by_report", True)),
            "destination_candidates": list(cand.get("destination_candidates") or []),
            "rejected": False,
        }
    return {
        "photo_type": f["photo_type"].get("value"),
        "manufacturer": f["manufacturer"].get("value"),
        "model": f["model"].get("value"),
        "serial": f["serial"].get("value"),
        "equipment_type": f["equipment_type"].get("value"),
        "equipment_tag": f["equipment_tag"].get("value") or None,
        "readings": photo["proposal"]["readings"],
        "visible_text": f["visible_text"].get("value") or None,
        "notes": None,
        "facts": facts,
        "status": "CONFIRMED",
        "source": "AUTO",
        "rejected_fields": [],
    }


class LabelServer(BaseHTTPRequestHandler):
    data_dir: Path
    labels_path: Path
    manifest: list
    inventory: list
    labels: dict
    photos: list
    metrics: dict

    @classmethod
    def configure(cls, data_dir: Path) -> None:
        cls.data_dir = data_dir
        cls.labels_path = data_dir / "labels.json"
        cls.manifest = load_json(data_dir / "manifest.json", [])
        if isinstance(cls.manifest, dict):
            cls.manifest = cls.manifest.get("imported", [])
        inv = load_json(data_dir / "inventory.json", {})
        cls.inventory = inv.get("inventory", []) if isinstance(inv, dict) else []
        raw_labels = load_json(cls.labels_path, {})
        cls.labels = {pid: normalize_label(l) for pid, l in raw_labels.items()}
        by_id = {p.get("photo_id"): p for p in cls.inventory}
        photos = []
        for entry in cls.manifest:
            pid = entry.get("photo_id")
            inv_entry = by_id.get(pid, {})
            decoded = Path(entry.get("decoded_path", ""))
            proposal = reconcile(inv_entry) if inv_entry else None
            photos.append({
                "photo_id": pid,
                "original_filename": entry.get("original_filename"),
                "decoded_rel": str(decoded.relative_to(data_dir)).replace("\\", "/")
                if decoded.is_relative_to(data_dir) else str(decoded),
                "candidate_class": inv_entry.get("candidate_class"),
                "candidate_confidence": inv_entry.get("candidate_confidence"),
                "candidate_facts": inv_entry.get("candidate_facts", []),
                "ocr_text": inv_entry.get("ocr_text", []),
                "seconds": inv_entry.get("seconds"),
                "label": cls.labels.get(pid),
                "proposal": proposal,
            })
        attach_sequences(photos)
        cls.photos = photos
        cls.metrics = cls.compute_metrics(photos)

    @staticmethod
    def compute_metrics(photos: list) -> dict:
        from collections import Counter
        verdicts = Counter(p["proposal"]["verdict"] for p in photos)
        autopop = sum(1 for p in photos
                      if autopopulated_fields(p["proposal"]) > 0)
        confirmed = sum(1 for p in photos
                        if p.get("label") and p["label"]["status"] == "CONFIRMED")
        total = len(photos)
        safe = verdicts["SAFE_CONFIRM"]
        needs = verdicts["NEEDS_REVIEW"]
        confl = verdicts["CONFLICTS"]
        unk = verdicts["UNKNOWN"]
        # clicks: 1 confirm click per photo; extra clicks for review/edit
        clicks = safe * 1 + needs * 4 + confl * 6 + unk * 5
        minutes = round((safe * 3 + needs * 15 + confl * 30 + unk * 25) / 60.0, 1)
        proposed_facts = sum(len(p["proposal"].get("facts") or []) for p in photos)
        confirmed_facts = 0
        for p in photos:
            lab = p.get("label") or {}
            for fact in (lab.get("facts") or {}).values():
                if fact.get("value") and not fact.get("rejected"):
                    confirmed_facts += 1
        return {
            "PHOTOS_TOTAL": total,
            "AUTOPOPULATED": autopop,
            "SAFE_CONFIRM": safe,
            "NEEDS_REVIEW": needs,
            "CONFLICTS": confl,
            "UNKNOWN": unk,
            "CONFIRMED": confirmed,
            "FACTS_PROPOSED": proposed_facts,
            "FACTS_CONFIRMED": confirmed_facts,
            "ESTIMATED_OWNER_CLICKS": clicks,
            "ESTIMATED_OWNER_REVIEW_MINUTES": minutes,
        }

    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write("[label] %s\n" % (fmt % args))

    # -- helpers ------------------------------------------------------------
    def send_json(self, obj, status=200):
        body = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _photo(self, photo_id: str) -> dict | None:
        return next((p for p in self.photos if p["photo_id"] == photo_id), None)

    def _photo_file(self, photo_id: str):
        """Resolve the decoded working copy, confined to the corpus root."""
        photo = self._photo(photo_id)
        if photo is None:
            return None, "no such photo"
        root = self.data_dir.resolve()
        try:
            resolved = (self.data_dir / photo["decoded_rel"]).resolve()
        except OSError:
            return None, "decoded file missing"
        if not resolved.is_relative_to(root):
            return None, "path outside corpus root"
        if not resolved.is_file():
            return None, "decoded file missing"
        return photo, resolved

    def _write_labels(self) -> None:
        tmp = self.labels_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.labels, indent=2), encoding="utf-8")
        tmp.replace(self.labels_path)

    def _apply_label(self, photo_id: str, label: dict) -> None:
        self.labels[photo_id] = label
        photo = self._photo(photo_id)
        if photo is not None:
            photo["label"] = label
        self._write_labels()
        type(self).metrics = self.compute_metrics(self.photos)
        attach_sequences(self.photos)

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/" or path == "/index.html":
            self.send_index()
        elif path == "/api/state":
            catalog = None
            if _CATALOG:
                catalog = {
                    "fields": {fid: {"DISPLAY_NAME": d["DISPLAY_NAME"], "UNIT": d["UNIT"],
                                     "SECTION": d["SECTION"], "DATA_TYPE": d["DATA_TYPE"]}
                               for fid, d in _CATALOG.FIELD_CATALOG_V1.items()},
                    "sections": list(_CATALOG.FIELD_SECTIONS),
                    "photo_types": list(_CATALOG.PHOTO_TYPE_SCHEMAS),
                }
            self.send_json({"photos": self.photos, "metrics": self.metrics,
                            "catalog": catalog})
        elif path == "/api/labels":
            self.send_json({"labels": self.labels})
        elif path.startswith("/api/images/"):
            self.send_image(path[len("/api/images/"):])
        elif path.startswith("/img/"):
            self.send_image(path[len("/img/"):])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/label/"):
            self.save_label(path[len("/api/label/"):])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/bulk-confirm":
            self.bulk_confirm()
        elif path.startswith("/api/action/"):
            parts = path[len("/api/action/"):].split("/")
            if len(parts) == 2:
                self.photo_action(parts[0], parts[1])
            else:
                self.send_json({"error": "not found"}, 404)
        else:
            self.send_json({"error": "not found"}, 404)

    # -- handlers -----------------------------------------------------------
    def send_index(self):
        page = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def send_image(self, photo_id: str):
        photo, path = self._photo_file(photo_id)
        if photo is None:
            self.send_json({"error": path}, 404)
            return
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def save_label(self, photo_id: str):
        photo = self._photo(photo_id)
        if photo is None:
            self.send_json({"error": "no such photo"}, 404)
            return
        body = self.read_body()
        status = (body.get("status") or "UNLABELED").upper()
        if status not in VALID_STATUSES:
            self.send_json({"error": f"status must be one of {VALID_STATUSES}"}, 400)
            return
        photo_type = (body.get("photo_type") or "").upper().strip()
        if photo_type and photo_type not in VALID_PHOTO_TYPES:
            self.send_json({"error": f"photo_type must be one of {VALID_PHOTO_TYPES}"}, 400)
            return
        readings = body.get("readings")
        if not isinstance(readings, list):
            readings = []
        cleaned = normalize_label({
            "photo_type": photo_type or None,
            "equipment_type": (body.get("equipment_type") or "").strip() or None,
            "equipment_tag": (body.get("equipment_tag") or "").strip() or None,
            "manufacturer": (body.get("manufacturer") or "").strip() or None,
            "model": (body.get("model") or "").strip() or None,
            "serial": (body.get("serial") or "").strip() or None,
            "readings": readings,
            "facts": body.get("facts"),
            "visible_text": (body.get("visible_text") or "").strip() or None,
            "notes": (body.get("notes") or "").strip() or None,
            "status": status,
            "source": body.get("source") or "MANUAL",
            "rejected_fields": body.get("rejected_fields") or [],
        })
        self._apply_label(photo_id, cleaned)
        self.send_json({"ok": True, "label": cleaned, "metrics": self.metrics})

    def photo_action(self, photo_id: str, action: str):
        photo = self._photo(photo_id)
        if photo is None:
            self.send_json({"error": "no such photo"}, 404)
            return
        if action == "not_useful":
            label = normalize_label({
                "photo_type": None, "manufacturer": None, "model": None,
                "serial": None, "equipment_type": None, "equipment_tag": None,
                "readings": [], "visible_text": None, "notes": None,
                "status": "NOT_USEFUL", "source": "NOT_USEFUL",
            })
            self._apply_label(photo_id, label)
            self.send_json({"ok": True, "label": label, "metrics": self.metrics})
        elif action == "confirm_photo":
            label = proposal_label(photo)
            label["source"] = "PHOTO_CONFIRMED"
            self._apply_label(photo_id, label)
            self.send_json({"ok": True, "label": label, "metrics": self.metrics})
        elif action == "reject_ai":
            f = photo["proposal"]["fields"]
            rejected = [k for k, v in f.items() if v.get("value")]
            label = normalize_label({
                "photo_type": None, "manufacturer": None, "model": None,
                "serial": None, "equipment_type": None, "equipment_tag": None,
                "readings": [], "facts": [], "visible_text": None, "notes": None,
                "status": "PARTIAL", "source": "REJECTED",
                "rejected_fields": rejected,
            })
            self._apply_label(photo_id, label)
            self.send_json({"ok": True, "label": label, "metrics": self.metrics})
        else:
            self.send_json({"error": f"unknown action {action}"}, 400)

    def bulk_confirm(self):
        body = self.read_body()
        requested = set(body.get("photo_ids") or [])
        confirmed = []
        for photo in self.photos:
            if photo["proposal"]["verdict"] != "SAFE_CONFIRM":
                continue
            if requested and photo["photo_id"] not in requested:
                continue
            if photo.get("label") and photo["label"]["status"] == "CONFIRMED":
                continue
            label = proposal_label(photo)
            self._apply_label(photo["photo_id"], label)
            confirmed.append(photo["photo_id"])
        self.send_json({"ok": True, "confirmed": confirmed,
                        "count": len(confirmed), "metrics": self.metrics})

    def log_request(self, code="-", size="-"):  # suppress default access log noise
        pass


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SCS Vision Corpus Labeling</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.45 system-ui, Segoe UI, sans-serif; background: #12141a; color: #e6e8ee; }
header { display: flex; align-items: center; gap: 14px; padding: 10px 16px; background: #1a1d26; border-bottom: 1px solid #2a2f3a; position: sticky; top: 0; z-index: 5; flex-wrap: wrap; }
header h1 { font-size: 15px; margin: 0; font-weight: 600; }
header .spacer { flex: 1; }
button, select, input, textarea { font: inherit; color: inherit; }
button { background: #232834; border: 1px solid #3a4150; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button:hover { background: #2c3342; }
button.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
button.primary:hover { background: #1d4ed8; }
button.green { background: #1e5e34; border-color: #2f8a4c; color: #d7f2df; }
button.green:hover { background: #287a45; }
button.danger { background: #5e1e1e; border-color: #8a2f2f; color: #f2d7d7; }
select { background: #232834; border: 1px solid #3a4150; border-radius: 6px; padding: 6px 8px; }
input, textarea { background: #171a21; border: 1px solid #3a4150; border-radius: 6px; padding: 6px 8px; width: 100%; }
label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #8b93a5; margin: 10px 0 4px; }
.fieldwrap { position: relative; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.green { background: #34d399; } .dot.yellow { background: #fbbf24; } .dot.red { background: #f87171; }
input.green, select.green, textarea.green { border-color: #2f8a4c; }
input.yellow, select.yellow, textarea.yellow { border-color: #b7791f; }
input.red, select.red, textarea.red { border-color: #c0392b; }
input.edited, select.edited, textarea.edited { border-color: #22d3ee; }
main { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(340px, 1fr); gap: 0; height: calc(100vh - 104px); }
#stage { display: flex; align-items: center; justify-content: center; background: #0b0d12; overflow: hidden; position: relative; }
#stage img { max-width: 100%; max-height: 100%; object-fit: contain; }
#panel { padding: 10px 16px 20px; overflow-y: auto; border-left: 1px solid #2a2f3a; }
#nav { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
#nav .count { color: #8b93a5; font-size: 13px; }
#progress { height: 4px; background: #2a2f3a; border-radius: 2px; overflow: hidden; }
#progress > div { height: 100%; background: #2563eb; width: 0; transition: width .2s; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.row.one { grid-template-columns: 1fr; }
.hint { font-size: 12px; color: #6b7280; margin-top: 4px; }
.ai { background: #1a222e; border: 1px solid #263449; border-radius: 8px; padding: 10px 12px; margin: 8px 0; }
.ai h3 { margin: 0 0 6px; font-size: 12px; color: #7aa2f7; text-transform: uppercase; letter-spacing: .06em; }
.ai .tag { display: inline-block; background: #263449; border-radius: 4px; padding: 1px 6px; margin: 2px 4px 2px 0; font-size: 12px; }
.ai .tag.green { background: #16381f; color: #a7e8bb; border: 1px solid #2f8a4c; }
.ai .tag.yellow { background: #3a2f14; color: #f3d9a0; border: 1px solid #b7791f; }
.ai .tag.red { background: #3a1616; color: #f0b3b3; border: 1px solid #c0392b; }
.assoc { background: #1c2433; border: 1px solid #2c3d5c; border-radius: 8px; padding: 8px 12px; margin: 8px 0; font-size: 12px; }
.assoc b { color: #9db8e8; }
#metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 6px; margin: 8px 0; }
#metrics div { background: #171b24; border: 1px solid #262c3a; border-radius: 6px; padding: 6px 8px; font-size: 12px; text-align: center; }
#metrics b { display: block; font-size: 16px; }
#metrics span { color: #8b93a5; font-size: 10px; text-transform: uppercase; letter-spacing: .05em; }
#statusMsg { position: fixed; bottom: 14px; right: 14px; background: #173a24; border: 1px solid #2f6b44; color: #b8e6c8; padding: 8px 14px; border-radius: 8px; opacity: 0; transition: opacity .25s; pointer-events: none; z-index: 10; }
#statusMsg.err { background: #3a1a1a; border-color: #6b2f2f; color: #e6b8b8; }
kbd { background: #232834; border: 1px solid #3a4150; border-radius: 4px; padding: 1px 5px; font-size: 11px; }
.legend { font-size: 11px; color: #8b93a5; display: flex; gap: 12px; margin: 6px 0; }
.legend .dot { vertical-align: middle; }
#verdict { font-weight: 700; }
#verdict.CONFLICTS { color: #f87171; } #verdict.NEEDS_REVIEW { color: #fbbf24; }
#verdict.SAFE_CONFIRM { color: #34d399; } #verdict.UNKNOWN { color: #9ca3af; }
#emptyNote { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #6b7280; }
#factSections { margin: 10px 0 4px; }
.section { border: 1px solid #2a2f3a; border-radius: 8px; padding: 8px 10px; margin: 8px 0; background: #161a22; }
.section h4 { margin: 0 0 6px; font-size: 11px; color: #8b93a5; text-transform: uppercase; letter-spacing: .08em; }
.frow { display: flex; align-items: center; gap: 8px; padding: 3px 0; border-bottom: 1px dashed #232936; font-size: 13px; }
.frow:last-child { border-bottom: none; }
.frow .fname { flex: 0 0 150px; color: #9aa4b5; font-size: 12px; }
.frow .fval { flex: 1; }
.frow .src { color: #6b7280; font-size: 11px; }
.frow.green .fval { color: #a7e8bb; }
.frow.yellow .fval { color: #f3d9a0; }
.frow.red .fval { color: #f0b3b3; }
.frow.confirmed .fval { color: #9fe3c0; }
.frow.absent .fval { color: #565e6e; font-style: italic; }
.frow.rejected .fval { color: #c0392b; text-decoration: line-through; }
button.mini { padding: 1px 8px; font-size: 11px; }
</style>
</head>
<body>
<header>
  <h1>SCS Vision Corpus &mdash; Ground Truth Labeling</h1>
  <span id="count" class="count">0/0 confirmed</span>
  <button class="green" id="bulkBtn" onclick="bulkConfirm()" title="Confirm every SAFE photo (OCR+VLM validated)">Confirm SAFE (0)</button>
  <div class="spacer"></div>
  <select id="filter" onchange="setFilter(this.value)">
    <option value="">All</option>
    <option value="NEEDS">Review mode (conflicts+needs+unknown)</option>
    <option value="CONFLICTS">Conflicts</option>
    <option value="NEEDS_REVIEW">Needs review</option>
    <option value="UNKNOWN">Unknown</option>
    <option value="SAFE">Safe</option>
    <option value="CONFIRMED">Confirmed</option>
    <option value="PARTIAL">Partial</option>
    <option value="NOT_USEFUL">Not useful</option>
  </select>
</header>
<div id="progress"><div id="progressBar"></div></div>
<main>
  <div id="stage"><img id="photo" alt="photo"><div id="emptyNote" style="display:none">No photos match filter</div></div>
  <div id="panel">
    <div id="nav">
      <button onclick="step(-1)">&larr; Prev</button>
      <button onclick="step(1)">Next &rarr;</button>
      <span class="count" id="position"></span>
      <span class="count" id="verdict"></span>
      <select id="jump" onchange="jump()"><option value="">Jump&hellip;</option></select>
    </div>

    <div id="metrics"></div>

    <div class="assoc" id="assocBox" style="display:none"></div>

    <div class="ai" id="aiBox">
      <h3>AI/OCR evidence (proposal &mdash; not ground truth)</h3>
      <div id="aiBody"></div>
    </div>

    <div class="legend">
      <span><span class="dot green"></span>corroborated</span>
      <span><span class="dot yellow"></span>uncertain</span>
      <span><span class="dot red"></span>conflict / known error</span>
      <span><span class="dot" style="background:#22d3ee"></span>confirmed / edited</span>
      <span><span class="dot" style="background:#565e6e"></span>not visible</span>
    </div>

    <div class="actions" style="display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 4px;">
      <button class="green" onclick="confirmAllProposed()">Confirm all proposed</button>
      <button class="green" onclick="confirmPhoto()">Confirm photo</button>
      <button onclick="toggleEdit()">Edit</button>
      <button class="danger" onclick="rejectAi()">Reject AI facts</button>
      <button class="danger" onclick="notUseful()">Not useful</button>
    </div>

    <div id="factSections"></div>

    <label>Photo type *</label>
    <div class="fieldwrap"><span id="dot_photo_type" class="dot yellow"></span>
      <select id="photo_type" oninput="edited(this)">
        <option value="">&mdash; select &mdash;</option>
        <option>NAMEPLATE</option><option>INSTRUMENT_READING</option><option>TEMP_RH_READING</option>
        <option>DUCTWORK</option><option>EQUIPMENT</option><option>SYSTEM_STATIC</option><option>OTHER</option>
      </select>
    </div>

    <div class="row">
      <div><label>Manufacturer</label><div class="fieldwrap"><span id="dot_manufacturer" class="dot yellow"></span><input id="manufacturer" autocomplete="off" oninput="edited(this)"></div></div>
      <div><label>Model</label><div class="fieldwrap"><span id="dot_model" class="dot yellow"></span><input id="model" autocomplete="off" oninput="edited(this)"></div></div>
    </div>
    <div class="row">
      <div><label>Serial</label><div class="fieldwrap"><span id="dot_serial" class="dot yellow"></span><input id="serial" autocomplete="off" oninput="edited(this)"></div></div>
      <div><label>Equipment type</label><div class="fieldwrap"><span id="dot_equipment_type" class="dot yellow"></span><input id="equipment_type" autocomplete="off" placeholder="RTU / AHU / VAV / Condensing unit&hellip;" oninput="edited(this)"></div></div>
    </div>
    <div class="row">
      <div><label>Equipment tag</label><div class="fieldwrap"><span id="dot_equipment_tag" class="dot yellow"></span><input id="equipment_tag" autocomplete="off" placeholder="RTU-1 (only if supported by evidence)" oninput="edited(this)"></div></div>
      <div><label>Visible readings</label><div class="fieldwrap"><span id="dot_readings" class="dot yellow"></span><input id="readings" autocomplete="off" placeholder="e.g. 48.2 / 11.4 / 73" oninput="edited(this)"></div></div>
    </div>
    <div class="row one">
      <label>Visible text (other than above)</label>
      <textarea id="visible_text" rows="2" placeholder="Any other readable text on the plate / display" oninput="edited(this)"></textarea>
    </div>
    <div class="row one">
      <label>Status</label>
      <select id="status" onchange="edited(this)">
        <option value="UNLABELED">UNLABELED</option><option value="PARTIAL">PARTIAL</option>
        <option value="CONFIRMED">CONFIRMED</option><option value="NOT_USEFUL">NOT USEFUL</option>
      </select>
      <div class="hint">CONFIRMED = all fields are complete and correct. Only CONFIRMED counts toward metrics.</div>
    </div>
    <div class="row one">
      <label>Notes</label>
      <textarea id="notes" rows="2" oninput="edited(this)"></textarea>
    </div>
  </div>
</main>
<div id="statusMsg"></div>
<script>
let photos = [];
let idx = 0;
let current = null;
let filter = "";
let metrics = {};
let catalog = null;
let fieldsDef = {};
let sections = [];
let factOverrides = {};

async function api(url, method, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  return r.json();
}
function showMsg(text, isErr) {
  const el = document.getElementById("statusMsg");
  el.textContent = text;
  el.className = isErr ? "err" : "";
  el.style.opacity = 1;
  clearTimeout(showMsg._t);
  showMsg._t = setTimeout(() => (el.style.opacity = 0), 2200);
}
function visibleList() {
  return photos.filter(p => {
    if (!filter) return true;
    if (filter === "NEEDS") return ["CONFLICTS", "NEEDS_REVIEW", "UNKNOWN"].includes(p.proposal.verdict);
    if (filter === "SAFE") return p.proposal.verdict === "SAFE_CONFIRM";
    if (filter === "CONFIRMED" || filter === "PARTIAL" || filter === "NOT_USEFUL")
      return (p.label || {}).status === filter;
    return p.proposal.verdict === filter;
  });
}
function render() {
  const list = visibleList();
  document.getElementById("emptyNote").style.display = list.length ? "none" : "flex";
  if (!list.length) { current = null; return; }
  if (idx >= list.length) idx = list.length - 1;
  if (idx < 0) idx = 0;
  current = list[idx];
  const id = current.photo_id;
  document.getElementById("photo").src = "/api/images/" + encodeURIComponent(id);
  document.getElementById("position").textContent = (idx + 1) + " / " + list.length + "  (" + id + ")";
  const v = document.getElementById("verdict");
  v.textContent = current.proposal.verdict;
  v.className = "count " + current.proposal.verdict;
  const l = current.label || {};
  const f = current.proposal.fields;
  setField("photo_type", valOf(l, "photo_type", f));
  setField("manufacturer", valOf(l, "manufacturer", f));
  setField("model", valOf(l, "model", f));
  setField("serial", valOf(l, "serial", f));
  setField("equipment_type", valOf(l, "equipment_type", f));
  setField("equipment_tag", valOf(l, "equipment_tag", f));
  document.getElementById("readings").value = (l.readings || []).map(r => r.value + (r.unit ? " " + r.unit : "")).join(" / ");
  document.getElementById("visible_text").value = valOf(l, "visible_text", f) || "";
  document.getElementById("status").value = l.status || "UNLABELED";
  document.getElementById("notes").value = l.notes || "";
  paintFields(f, l);
  renderAI();
  renderSections();
  renderAssoc();
  document.getElementById("jump").value = id;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function renderSections() {
  const box = document.getElementById("factSections");
  if (!current) { box.innerHTML = ""; return; }
  const schema = current.proposal.expected || [];
  const absent = current.proposal.absent_fields || {};
  const pf = {};
  (current.proposal.facts || []).forEach(f => { pf[f.field_type] = f; });
  const lf = ((current.label || {}).facts || {});
  const bySec = {};
  for (const fid of schema) {
    const sec = (fieldsDef[fid] && fieldsDef[fid].SECTION) || "OTHER_VISIBLE_DATA";
    (bySec[sec] = bySec[sec] || []).push(fid);
  }
  const secOrder = sections.length ? sections : Object.keys(bySec);
  const parts = [];
  for (const sec of secOrder) {
    const fids = bySec[sec] || [];
    if (!fids.length) continue;
    parts.push(`<div class="section"><h4>${sec.replace(/_/g, " ")}</h4>`);
    for (const fid of fids) parts.push(factRow(fid, fieldsDef[fid], pf[fid], lf[fid], absent[fid]));
    parts.push("</div>");
  }
  box.innerHTML = parts.join("\\n") || "";
}
function factRow(fid, def, pf, lf, abs) {
  const label = def ? def.DISPLAY_NAME : fid.replace(/_/g, " ");
  const unit = def ? def.UNIT : "";
  const ov = factOverrides[fid] || {};
  const rejected = ov.rejected === undefined ? (lf ? !!lf.rejected : false) : ov.rejected;
  if (rejected) {
    return `<div class="frow rejected" id="frow_${fid}"><span class="fname">${label}</span><span class="fval">REJECTED</span><button class="mini" onclick="toggleFact('${fid}',false)">Undo</button></div>`;
  }
  if (lf && lf.value != null && lf.value !== "") {
    return `<div class="frow confirmed" id="frow_${fid}"><span class="fname">${label}</span><span class="fval">${esc(lf.value)} ${unit} <span class="src">(${lf.source_class || "PHOTO_CONFIRMED"}, conf ${lf.confidence})</span></span><button class="mini" onclick="toggleFact('${fid}',true)">Reject</button></div>`;
  }
  if (pf) {
    const st = pf.error_class ? "red" : (pf.corroboration === "OCR+VLM" ? "green" : (pf.needs_confirmation ? "yellow" : "green"));
    const why = pf.error_class ? " (" + pf.error_class + ")" : "";
    return `<div class="frow ${st}" id="frow_${fid}"><span class="fname">${label}</span><span class="fval">${esc(pf.value)} ${unit} <span class="src">${pf.extraction_method || "?"}${why}${pf.confidence ? " conf " + pf.confidence : ""}</span></span><button class="mini" onclick="toggleFact('${fid}',true)">Reject</button></div>`;
  }
  return `<div class="frow absent" id="frow_${fid}"><span class="fname">${label}</span><span class="fval">not visible</span></div>`;
}
function toggleFact(fid, rejected) {
  factOverrides[fid] = { rejected };
  renderSections();
}
function valOf(l, key, f) {
  if (l.status && l[key] != null) return l[key];
  return f[key].value || "";
}
function setField(id, v) { document.getElementById(id).value = v; }
function paintFields(f, l) {
  const edited = l.status === "CONFIRMED" || l.status === "PARTIAL" || l.status === "NOT_USEFUL";
  for (const key of ["photo_type", "manufacturer", "model", "serial", "equipment_type", "equipment_tag"]) {
    const el = document.getElementById(key);
    const dot = document.getElementById("dot_" + key);
    el.className = edited ? "edited" : (f[key].status || "yellow");
    dot.className = "dot " + (edited ? "yellow" : (f[key].status || "yellow"));
  }
  const rd = document.getElementById("readings");
  rd.className = edited ? "edited" : "yellow";
}
function renderAI() {
  const box = document.getElementById("aiBody");
  if (!current) { box.innerHTML = ""; return; }
  const f = current.proposal.fields;
  const parts = [];
  for (const key of ["photo_type", "manufacturer", "model", "serial", "equipment_type", "equipment_tag"]) {
    const field = f[key];
    const v = field.value || "UNKNOWN";
    const label = key.replace(/_/g, " ");
    const extra = [];
    if (field.error_class) extra.push(field.error_class);
    if (field.source) extra.push(field.source);
    if (field.alternatives && field.alternatives.length)
      extra.push("alt: " + field.alternatives.join(" / "));
    parts.push(`<span class="tag ${field.status}">${label}: ${v}${extra.length ? " (" + extra.join(", ") + ")" : ""}</span>`);
  }
  const reads = (current.proposal.readings || []).map(r =>
    `<span class="tag">${r.reading_type} ${r.value} ${r.unit || ""}</span>`).join("");
  if (reads) parts.push(`<div style="margin-top:6px">nameplate: ${reads}</div>`);
  const ocr = (current.ocr_text || []).map(o => (o.text || "")).filter(Boolean).join(" | ");
  if (ocr) parts.push(`<div style="margin-top:6px;color:#9aa4b5">OCR: ${ocr}</div>`);
  if (!current.proposal.readings || !current.proposal.readings.length)
    parts.push(`<div style="margin-top:6px;color:#9aa4b5">${current.proposal.nameplate}</div>`);
  box.innerHTML = parts.join("\\n") || "<span>No evidence available.</span>";
}
function renderAssoc() {
  const box = document.getElementById("assocBox");
  if (current && current.proposed_equipment) {
    box.style.display = "block";
    box.innerHTML = `<b>PROPOSED_EQUIPMENT=${current.proposed_equipment}</b> &mdash; ${current.association_reason} &middot; CONFIDENCE=${current.association_confidence} ` +
      `<button onclick="applyAssoc()">Apply tag</button>`;
  } else { box.style.display = "none"; }
}
function applyAssoc() {
  if (!current) return;
  document.getElementById("equipment_tag").value = current.proposed_equipment;
  document.getElementById("equipment_tag").className = "edited";
  showMsg("Equipment tag applied: " + current.proposed_equipment);
}
function collect() {
  const txt = val("readings");
  const manual = txt ? txt.split("/").map(s => s.trim()).filter(Boolean)
      .map(v => ({ reading_type: "MANUAL", value: v, unit: "", source_photo: current.photo_id, confidence: 1.0 })) : [];
  const auto = (current.proposal.readings || []).map(r => ({ ...r, source_photo: current.photo_id }));
  const readings = manual.length ? manual : auto;
  const factSrc = {};
  (current.proposal.facts || []).forEach(f => { factSrc[f.field_type] = f; });
  const lf = ((current.label || {}).facts || {});
  const facts = [];
  const fids = new Set([...Object.keys(factSrc), ...Object.keys(lf)]);
  for (const fid of fids) {
    const s = lf[fid] || factSrc[fid];
    if (!s) continue;
    const ov = factOverrides[fid] || {};
    facts.push({
      field_type: fid,
      value: (lf[fid] && lf[fid].value != null) ? lf[fid].value : (factSrc[fid] ? factSrc[fid].value : null),
      unit: s.unit || "",
      source_class: lf[fid] ? (lf[fid].source_class || "PHOTO_CONFIRMED") : (factSrc[fid] && factSrc[fid].source_class ? factSrc[fid].source_class : "PHOTO_VLM"),
      confidence: s.confidence != null ? s.confidence : 1.0,
      extraction_method: s.extraction_method || "MANUAL",
      corroboration: s.corroboration || "SINGLE",
      needs_confirmation: !!s.needs_confirmation,
      expected_by_report: !!s.expected_by_report,
      destination_candidates: s.destination_candidates || [],
      rejected: ov.rejected === undefined ? (lf[fid] ? !!lf[fid].rejected : false) : !!ov.rejected,
    });
  }
  return {
    photo_type: val("photo_type"), equipment_type: val("equipment_type"),
    equipment_tag: val("equipment_tag"), manufacturer: val("manufacturer"),
    model: val("model"), serial: val("serial"),
    readings, facts, visible_text: val("visible_text"), notes: val("notes"),
    status: val("status") || "UNLABELED", source: "EDIT",
  };
}
function val(id) { return document.getElementById(id).value.trim(); }
function edited(el) {
  if (el.id !== "status") el.classList.add("edited");
}
function toggleEdit() {
  document.querySelectorAll("#panel input, #panel select, #panel textarea").forEach(el => el.classList.add("edited"));
  showMsg("Edit mode: all fields are editable. Save to keep changes.");
}
async function save(silent) {
  if (!current) return false;
  const body = collect();
  if (body.status === "CONFIRMED" && !body.photo_type) {
    showMsg("CONFIRMED requires a photo type", true); return false;
  }
  const r = await api("/api/label/" + encodeURIComponent(current.photo_id), "PUT", body);
  if (r.ok) { current.label = r.label; metrics = r.metrics; renderMetrics(); updateCounts(); if (!silent) showMsg("Saved " + current.photo_id); return true; }
  showMsg("Save failed: " + (r.error || "unknown"), true); return false;
}
async function confirmAllProposed() {
  if (!current) return;
  const s = document.getElementById("status");
  s.value = "CONFIRMED";
  if (await save(false)) showMsg("Confirmed " + current.photo_id);
}
async function confirmPhoto() {
  if (!current) return;
  const r = await api("/api/action/" + encodeURIComponent(current.photo_id) + "/confirm_photo", "POST", {});
  if (r.ok) {
    current.label = r.label;
    factOverrides = {};
    renderSections();
    updateCounts(); renderMetrics();
    showMsg("Photo confirmed: " + current.photo_id);
  } else showMsg("Confirm failed: " + (r.error || "unknown"), true);
}
async function rejectAi() {
  if (!current) return;
  const r = await api("/api/action/" + encodeURIComponent(current.photo_id) + "/reject_ai", "POST", {});
  if (r.ok) {
    current.label = r.label;
    factOverrides = {};
    document.querySelectorAll("#panel input, #panel select, #panel textarea").forEach(el => el.value = el.id === "status" ? "PARTIAL" : "");
    renderSections();
    updateCounts(); renderMetrics();
    showMsg("AI facts rejected for " + current.photo_id + " - enter values manually");
  } else showMsg("Reject failed: " + (r.error || "unknown"), true);
}
async function notUseful() {
  if (!current) return;
  const r = await api("/api/action/" + encodeURIComponent(current.photo_id) + "/not_useful", "POST", {});
  if (r.ok) {
    current.label = r.label;
    factOverrides = {};
    document.querySelectorAll("#panel input, #panel select, #panel textarea").forEach(el => el.value = el.id === "status" ? "NOT_USEFUL" : "");
    renderSections();
    updateCounts(); renderMetrics();
    showMsg("Marked NOT USEFUL: " + current.photo_id);
  } else showMsg("Action failed: " + (r.error || "unknown"), true);
}
async function bulkConfirm() {
  const r = await api("/api/bulk-confirm", "POST", { all_safe: true });
  if (r.ok) {
    if (r.count > 0) showMsg("Bulk confirmed " + r.count + " safe photos: " + r.confirmed.join(", "));
    else showMsg("No safe photos remaining to confirm");
    metrics = r.metrics; renderMetrics(); updateCounts();
  } else showMsg("Bulk confirm failed", true);
}
function step(delta) {
  const list = visibleList();
  if (!list.length) return;
  idx = (idx + delta + list.length) % list.length;
  render();
}
function jump() { const id = document.getElementById("jump").value; if (id) { const i = visibleList().findIndex(p => p.photo_id === id); if (i >= 0) { idx = i; render(); } } }
function setFilter(v) { filter = v; idx = 0; render(); }
function updateCounts() {
  const n = photos.filter(p => p.label && p.label.status === "CONFIRMED").length;
  const t = photos.length;
  document.getElementById("count").textContent = n + "/" + t + " confirmed";
  document.getElementById("progressBar").style.width = (100 * n / t).toFixed(1) + "%";
  const sel = document.getElementById("jump");
  const prev = sel.value;
  sel.innerHTML = `<option value="">Jump&hellip;</option>` + photos.map(p =>
    `<option value="${p.photo_id}">${p.photo_id} ${(p.label ? p.label.status : "")} ${p.proposal.verdict}</option>`).join("");
  sel.value = prev;
}
function renderMetrics() {
  const m = metrics || {};
  const box = document.getElementById("metrics");
  const items = [
    ["PHOTOS_TOTAL", m.PHOTOS_TOTAL], ["AUTOPOPULATED", m.AUTOPOPULATED],
    ["SAFE_CONFIRM", m.SAFE_CONFIRM], ["NEEDS_REVIEW", m.NEEDS_REVIEW],
    ["CONFLICTS", m.CONFLICTS], ["UNKNOWN", m.UNKNOWN],
    ["CONFIRMED", m.CONFIRMED], ["~CLICKS", m.ESTIMATED_OWNER_CLICKS],
    ["~MIN", m.ESTIMATED_OWNER_REVIEW_MINUTES],
  ];
  box.innerHTML = items.map(([k, v]) => `<div><b>${v ?? "-"}</b><span>${k}</span></div>`).join("");
  const safe = m.SAFE_CONFIRM || 0;
  document.getElementById("bulkBtn").textContent = "Confirm SAFE (" + safe + ")";
}
document.getElementById("filter").addEventListener("change", e => setFilter(e.target.value));
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowRight") step(1);
  else if (e.key === "ArrowLeft") step(-1);
  else if (e.key === "Enter") confirmAllProposed();
});
(async () => {
  const state = await api("/api/state", "GET");
  photos = state.photos;
  metrics = state.metrics || {};
  catalog = state.catalog || null;
  if (catalog) {
    fieldsDef = catalog.fields || {};
    sections = catalog.sections || [];
    const sel = document.getElementById("photo_type");
    const existing = new Set([...sel.options].map(o => o.value));
    (catalog.photo_types || []).forEach(pt => {
      if (!existing.has(pt)) {
        const o = document.createElement("option");
        o.value = pt; o.textContent = pt;
        sel.appendChild(o);
      }
    });
  }
  photos.forEach(p => { if (!p.label) p.label = { status: "UNLABELED" }; });
  renderMetrics();
  updateCounts();
  render();
})();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3210)
    parser.add_argument("--data", default=r"C:\SCS_DATA\vision-benchmark\real")
    args = parser.parse_args()
    data_dir = Path(args.data)
    if not (data_dir / "manifest.json").exists():
        print(f"[label] manifest not found in {data_dir}", file=sys.stderr)
        return 2
    LabelServer.configure(data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), LabelServer)
    print(f"[label] serving {len(LabelServer.photos)} photos at http://127.0.0.1:{args.port}")
    print(f"[label] metrics: {json.dumps(LabelServer.metrics)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())