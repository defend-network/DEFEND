"""Local SCS report data layout under the SCS data root.

SCS_DATA/
├── masters/            (immutable; sha256 registry in config/masters.sha256)
├── contractors/        companies.json (saved contractors, reusable)
├── config/
├── jobs/JOB_ID/
│   ├── originals/      (never modified)
│   ├── extracted/
│   ├── working/
│   ├── output/
│   ├── job.json        (structured job record)
│   └── evidence.json   (evidence manifest)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import JobRecord, PhotoEvidence, PhotoClassification, Contractor

_SCS_DATA_ROOT_DEFAULT = Path(r"C:\SCS_DATA")
_MASTER_FILENAMES = (
    "Field_Report_Master.xlsm",
    "Test and Balance MASTER TEMPLATE 001.xlsx",
    "SCS-CrunchFitness.xlsx",
    "SCS-Gatorade-Report.xlsm",
    "SCS-LakePanasoffkee-Traverse.xlsx",
    "SCS-Roland-VAV.xlsx",
    "SCS-BP-RTU-Data-Only.xlsx",
)


def scs_data_root() -> Path:
    raw = os.environ.get("SCS_DATA_ROOT", "")
    if raw and raw.strip():
        return Path(raw.strip())
    return _SCS_DATA_ROOT_DEFAULT


class ReportPaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or scs_data_root()).resolve()
        self.masters = self.root / "masters"
        self.contractors = self.root / "contractors"
        self.config = self.root / "config"
        self.jobs = self.root / "jobs"

    def ensure(self) -> "ReportPaths":
        for directory in (
            self.masters,
            self.contractors,
            self.config,
            self.jobs,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def job_dir(self, job_id: str) -> Path:
        return self.jobs / job_id

    def job_subdir(self, job_id: str, name: str) -> Path:
        directory = self.job_dir(job_id) / name
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def output_dir(self, job_id: str) -> Path:
        return self.job_subdir(job_id, "output")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MasterStore:
    def __init__(self, paths: ReportPaths | None = None) -> None:
        self.paths = paths or ReportPaths().ensure()

    def registry_file(self) -> Path:
        return self.paths.config / "masters.sha256.json"

    def install_masters(self, source_dir: Path) -> dict[str, str]:
        self.paths.ensure()
        source_dir = source_dir.resolve()
        for filename in _MASTER_FILENAMES:
            source = source_dir / filename
            if not source.exists():
                raise FileNotFoundError(f"master not found: {source}")
            destination = self.paths.masters / filename
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
        return self.record_hashes()

    def record_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for filename in _MASTER_FILENAMES:
            path = self.paths.masters / filename
            if path.exists():
                hashes[filename] = sha256_of(path)
        self.registry_file().write_text(
            json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8"
        )
        return hashes

    def verify_unchanged(self) -> tuple[bool, dict[str, str]]:
        expected = self.load_hashes()
        actual = self.current_hashes()
        changed = {
            name: value
            for name, value in expected.items()
            if actual.get(name) != value
        }
        return (not changed), changed

    def load_hashes(self) -> dict[str, str]:
        path = self.registry_file()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def current_hashes(self) -> dict[str, str]:
        return {
            filename: sha256_of(self.paths.masters / filename)
            for filename in _MASTER_FILENAMES
            if (self.paths.masters / filename).exists()
        }

    def list_masters(self) -> list[Path]:
        return sorted(self.paths.masters.glob("*"))


class ContractorStore:
    def __init__(self, paths: ReportPaths | None = None) -> None:
        self.paths = paths or ReportPaths().ensure()

    def _file(self) -> Path:
        return self.paths.contractors / "companies.json"

    def load(self) -> list[Contractor]:
        path = self._file()
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [Contractor.from_dict(item) for item in payload]

    def save(self, contractors: list[Contractor]) -> None:
        self.paths.ensure()
        payload = [c.to_dict() for c in contractors]
        self._file().write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def add(self, contractor: Contractor) -> Contractor:
        contractors = self.load()
        names = {c.company_name.casefold() for c in contractors}
        if contractor.company_name.casefold() in names:
            raise ValueError("contractor already exists")
        contractors.append(contractor)
        self.save(contractors)
        return contractor

    def find(self, company_name: str) -> Contractor | None:
        key = company_name.casefold()
        for contractor in self.load():
            if contractor.company_name.casefold() == key:
                return contractor
        return None


def _job_id() -> str:
    return f"scs_job_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


class JobStore:
    def __init__(self, paths: ReportPaths | None = None) -> None:
        self.paths = paths or ReportPaths().ensure()

    def create(self, record: JobRecord) -> JobRecord:
        self.paths.ensure()
        directory = self.paths.job_dir(record.metadata.job_id)
        if directory.exists():
            raise ValueError(f"job already exists: {record.metadata.job_id}")
        for name in ("originals", "extracted", "working", "output"):
            self.paths.job_subdir(record.metadata.job_id, name)
        self.save(record)
        return record

    def save(self, record: JobRecord) -> JobRecord:
        record.metadata.updated_at = datetime.now()
        (self.paths.job_dir(record.metadata.job_id) / "job.json").write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return record

    def load(self, job_id: str) -> JobRecord:
        path = self.paths.job_dir(job_id) / "job.json"
        if not path.exists():
            raise FileNotFoundError(f"no such job: {job_id}")
        return JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def exists(self, job_id: str) -> bool:
        return (self.paths.job_dir(job_id) / "job.json").exists()

    def list_jobs(self) -> list[str]:
        if not self.paths.jobs.exists():
            return []
        return sorted(
            directory.name
            for directory in self.paths.jobs.iterdir()
            if (directory / "job.json").exists()
        )

    def save_evidence(self, job_id: str, photos: list[PhotoEvidence]) -> None:
        path = self.paths.job_dir(job_id) / "evidence.json"
        path.write_text(
            json.dumps([p.to_dict() for p in photos], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_evidence(self, job_id: str) -> list[PhotoEvidence]:
        path = self.paths.job_dir(job_id) / "evidence.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [PhotoEvidence.from_dict(item) for item in payload]

    def load_json(self, job_id: str, filename: str) -> Any:
        path = self.paths.job_dir(job_id) / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, job_id: str, filename: str, payload: Any) -> None:
        path = self.paths.job_dir(job_id) / filename
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def next_output_version(self, job_id: str, stem: str) -> Path:
        output = self.paths.output_dir(job_id)
        version = 1
        while True:
            suffix = "" if version == 1 else f"_v{version:02d}"
            candidate = output / f"{stem}{suffix}.xlsx"
            if not candidate.exists():
                return candidate
            version += 1

    def original_dir(self, job_id: str) -> Path:
        return self.paths.job_subdir(job_id, "originals")


class PhotoIngest:
    """Copy originals unchanged, record manifest entries with sha256.

    Vision analysis may use copies under extracted/; originals are never
    modified. Classification/extraction run through the vision provider.
    """

    def __init__(self, paths: ReportPaths | None = None) -> None:
        self.paths = paths or ReportPaths().ensure()

    def ingest(
        self,
        job_id: str,
        source_files: list[Path],
        *,
        classifier=None,
    ) -> list[PhotoEvidence]:
        destination = self.paths.job_subdir(job_id, "originals")
        entries: list[PhotoEvidence] = []
        for index, source in enumerate(source_files, start=1):
            if not source.exists():
                raise FileNotFoundError(f"photo not found: {source}")
            target = destination / source.name
            if not target.exists():
                shutil.copy2(source, target)
            digest = sha256_of(target)
            classification = PhotoClassification.UNKNOWN
            confidence = None
            candidate_facts: list[dict[str, Any]] = []
            if classifier is not None:
                classification, confidence = classifier.classify_photo(target)
                classification = classification or PhotoClassification.UNKNOWN
                nameplate_facts = getattr(classifier, "candidate_nameplate_facts", None)
                display_facts = getattr(classifier, "candidate_display_facts", None)
                if nameplate_facts is not None:
                    candidate_facts.extend(nameplate_facts(target) or [])
                if display_facts is not None:
                    candidate_facts.extend(display_facts(target) or [])
            entries.append(
                PhotoEvidence(
                    photo_id=f"PHOTO-{index:03d}",
                    original_filename=source.name,
                    sha256=digest,
                    classification=classification,
                    confidence=confidence,
                    candidate_facts=candidate_facts,
                )
            )
        return entries