"""SCS field report command-line workflow.

    python -m scs_reports.cli init-masters --source <dir>
    python -m scs_reports.cli contractors add --company "Remedy Heating and Cooling"
    python -m scs_reports.cli job create --project "..." --site "..." ...
    python -m scs_reports.cli job add-photo JOB_ID file.jpg [file2.jpg ...]
    python -m scs_reports.cli job add-equipment JOB_ID --type RTU --tag RTU-1 ...
    python -m scs_reports.cli job add-reading JOB_ID RTU-1 --field airflow_cfm --value 2450 --unit cfm
    python -m scs_reports.cli job add-air-device JOB_ID --device OA-1 --function "Outside Air" ...
    python -m scs_reports.cli job plan JOB_ID
    python -m scs_reports.cli job compose JOB_ID
    python -m scs_reports.cli job validate JOB_ID
    python -m scs_reports.cli smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from .schema import (
    JobRecord,
    JobMetadata,
    Contractor,
    Equipment,
    EquipmentType,
    Measurement,
    AirDevice,
    Traverse,
    TraversePoint,
    Finding,
    Provenance,
)
from .store import (
    ReportPaths,
    MasterStore,
    ContractorStore,
    JobStore,
    PhotoIngest,
)
from .planner import plan_for
from .composer import Composer, output_stem
from .validation import validate_report
from .vision import ModelRouter


def _paths(args) -> ReportPaths:
    return ReportPaths().ensure()


def _store(args) -> JobStore:
    return JobStore(_paths(args))


def cmd_init_masters(args) -> int:
    source = Path(args.source).resolve()
    masters = MasterStore(_paths(args))
    hashes = masters.install_masters(source)
    print(f"installed {len(hashes)} masters into {masters.paths.masters}")
    unchanged, changed = masters.verify_unchanged()
    print(f"registry match: {unchanged}")
    return 0


def cmd_masters_status(args) -> int:
    masters = MasterStore(_paths(args))
    unchanged, changed = masters.verify_unchanged()
    if not masters.load_hashes():
        print("no registry; run init-masters")
        return 0
    print(f"master immutability: {'PASS' if unchanged else 'FAIL'}")
    for name, digest in masters.current_hashes().items():
        mark = "ok" if digest == masters.load_hashes().get(name) else "CHANGED"
        print(f"  {name}: {digest[:12]}... {mark}")
    return 0


def cmd_contractors(args) -> int:
    store = ContractorStore(_paths(args))
    if args.action == "list":
        contractors = store.load()
        if not contractors:
            print("no saved contractors (system starts empty)")
            return 0
        for contractor in contractors:
            print(
                f"{contractor.company_name}"
                + (f" | {contractor.contact}" if contractor.contact else "")
            )
        return 0
    if args.action == "add":
        contractor = store.add(
            Contractor(
                company_name=args.company,
                contact=args.contact,
                email=args.email,
                phone=args.phone,
                address=args.address,
                notes=args.notes,
            )
        )
        print(f"saved contractor: {contractor.company_name}")
        return 0
    return 2


def cmd_job_create(args) -> int:
    store = _store(args)
    metadata = JobMetadata(
        job_id=args.job_id or f"scs_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        project_name=args.project,
        project_number=args.number,
        site_name=args.site,
        site_address=args.address,
        test_date=(
            date.fromisoformat(args.test_date) if args.test_date else None
        ),
        technician=args.technician,
        hiring_contractor=args.contractor,
        customer=args.customer,
        design_engineer=args.engineer,
        report_type="TAB",
    )
    record = JobRecord(metadata=metadata)
    store.create(record)
    print(f"job created: {metadata.job_id}")
    print(f"  path: {store.paths.job_dir(metadata.job_id)}")
    return 0


def cmd_job_show(args) -> int:
    record = _store(args).load(args.job_id)
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0


def cmd_job_add_photo(args) -> int:
    store = _store(args)
    router = ModelRouter()
    photos = PhotoIngest(store.paths).ingest(
        args.job_id,
        [Path(p) for p in args.files],
        classifier=router,
    )
    record = store.load(args.job_id)
    existing = {p.original_filename for p in record.photos}
    for photo in photos:
        if photo.original_filename in existing:
            print(f"skipped duplicate: {photo.original_filename}")
            continue
        record.photos.append(photo)
        print(
            f"ingested {photo.photo_id}: {photo.original_filename} "
            f"sha256={photo.sha256[:12]}... class={photo.classification.value}"
        )
    store.save(record)
    store.save_evidence(args.job_id, record.photos)
    return 0


def cmd_job_add_equipment(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    equipment = Equipment(
        equipment_id=args.tag,
        equipment_type=EquipmentType(args.equipment_type),
        tag=args.tag,
        manufacturer=args.manufacturer,
        model=args.model,
        serial=args.serial,
        area_served=args.area,
        notes=args.notes,
    )
    record.equipment.append(equipment)
    store.save(record)
    print(f"added equipment: {equipment.equipment_id} ({equipment.equipment_type.value})")
    return 0


def cmd_job_add_reading(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    equipment = next(
        (e for e in record.equipment if e.equipment_id == args.equipment),
        None,
    )
    if equipment is None:
        print(f"no such equipment: {args.equipment}", file=sys.stderr)
        return 2
    equipment.measurements.append(
        Measurement(
            field=args.field,
            value=args.value,
            unit=args.unit or "",
            source_type=Provenance.TECH_ENTERED,
            technician_confirmed=True,
        )
    )
    store.save(record)
    print(f"{equipment.equipment_id}.{args.field} = {args.value} {args.unit or ''}")
    return 0


def cmd_job_add_air_device(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    record.air_devices.append(
        AirDevice(
            device_id=args.device,
            function=args.function,
            area_served=args.area,
            design_cfm=args.design_cfm,
            final_cfm=args.final_cfm,
            measurement_method=args.method,
            size=args.size,
            avg_velocity_fpm=args.velocity,
            status=args.status,
            notes=args.notes,
        )
    )
    store.save(record)
    print(f"added air device: {args.device} ({args.function})")
    return 0


def cmd_job_add_traverse(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    points = []
    for token in args.points or []:
        label, column, fpm = token.split(":")
        points.append(TraversePoint(label.upper(), float(fpm), int(column)))
    record.traverses.append(
        Traverse(
            traverse_id=args.id,
            system_id=args.system,
            location=args.location,
            duct_size=args.duct_size,
            area_sqft=args.area_sqft,
            design_fpm=args.design_fpm,
            final_fpm=args.final_fpm,
            sp=args.sp,
            points=points,
        )
    )
    store.save(record)
    print(f"added traverse: {args.id} ({args.system})")
    return 0


def cmd_job_add_finding(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    record.findings.append(
        Finding(title=args.title, detail=args.detail, severity=args.severity)
    )
    store.save(record)
    print(f"added finding: {args.title}")
    return 0


def cmd_job_set_notes(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    if args.scope is not None:
        record.scope_notes = args.scope
    if args.observations is not None:
        record.field_observations = args.observations
    if args.deficiencies is not None:
        record.known_deficiencies = args.deficiencies
    if args.notes is not None:
        record.technician_notes = args.notes
    store.save(record)
    print("notes updated")
    return 0


def cmd_job_plan(args) -> int:
    record = _store(args).load(args.job_id)
    plan = plan_for(record)
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    store = _store(args)
    store.write_json(args.job_id, "plan.json", plan.to_dict())
    print(f"plan saved to {store.paths.job_dir(args.job_id) / 'plan.json'}")
    return 0


def cmd_job_compose(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    plan_payload = store.load_json(args.job_id, "plan.json")
    if plan_payload is None:
        print("no saved plan; run `job plan` first", file=sys.stderr)
        return 2
    from .planner import ReportPlan

    plan = ReportPlan.from_dict(plan_payload)
    composer = Composer(store.paths, store)
    output = composer.compose(record, plan)
    print(f"composed: {output}")
    return 0


def cmd_job_validate(args) -> int:
    store = _store(args)
    record = store.load(args.job_id)
    plan_payload = store.load_json(args.job_id, "plan.json")
    if plan_payload is None:
        print("no saved plan; run `job plan` first", file=sys.stderr)
        return 2
    from .planner import ReportPlan

    plan = ReportPlan.from_dict(plan_payload)
    output = Path(args.output) if args.output else None
    if output is None:
        candidates = sorted(store.paths.output_dir(args.job_id).glob("*.xlsx"))
        if not candidates:
            print("no composed workbook; run `job compose` first", file=sys.stderr)
            return 2
        output = candidates[-1]
    report = validate_report(record, plan, output, masters=MasterStore(store.paths))
    for check in report.checks:
        print(f"  [{check.status:5s}] {check.name}: {check.message}")
    print(f"SUMMARY: {report.summary()}")
    return 1 if report.blocked else 0


def _sample_photos(count: int = 5, directory: Path | None = None) -> list[Path]:
    target = directory or Path(r"C:\SCS_DATA\working\sample-photos")
    target.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    labels = ("nameplate", "display", "airflow", "pressure", "ductwork")
    for index, label in enumerate(labels[:count], start=1):
        path = target / f"sample_{label}_{index}.txt"
        if not path.exists():
            path.write_text(
                f"sample field evidence {index} ({label})\n", encoding="utf-8"
            )
        files.append(path)
    return files


def cmd_smoke(args) -> int:
    paths = ReportPaths().ensure()
    store = JobStore(paths)
    contractor_store = ContractorStore(paths)

    if contractor_store.find("Remedy Heating and Cooling") is None:
        contractor_store.add(
            Contractor(
                company_name="Remedy Heating and Cooling",
                contact="Aaron Thomas",
                phone="(863) 555-0132",
            )
        )

    metadata = JobMetadata(
        job_id="smoke_tab_job",
        project_name="Synthetic Smoke Warehouse",
        project_number="999999",
        site_name="Smoke Test Site",
        site_address="1 Test Lane, Lakeland FL",
        test_date=date.today(),
        technician="Aaron Thomas",
        hiring_contractor="Remedy Heating and Cooling",
        report_type="TAB",
    )
    record = JobRecord(metadata=metadata)
    record.scope_notes = (
        "Synthetic smoke job exercising the full field-report pipeline: "
        "form, ingest, structured record, plan, compose, validate."
    )
    record.field_observations = (
        "Units operating in occupied mode during testing; all readings "
        "taken with calibrated instruments."
    )
    record.technician_notes = "Smoke job data is synthetic and for validation only."

    rtu = Equipment(
        equipment_id="RTU-1",
        equipment_type=EquipmentType.RTU,
        tag="RTU-1",
        manufacturer="Carrier",
        model="50TC-E08A2A5A0A0G0",
        serial="1320P93940",
        area_served="Conditioned gym",
    )
    rtu.measurements = [
        Measurement("refrigerant", "R-410A", "", Provenance.TECH_ENTERED, technician_confirmed=True),
        Measurement("voltage", 208, "volts", Provenance.TECH_ENTERED, technician_confirmed=True),
        Measurement("phase", 3, "", Provenance.TECH_ENTERED, technician_confirmed=True),
    ]
    rtu.notes = "Nameplate photographed; condition clear and legible."

    vav = Equipment(
        equipment_id="VAV-2-18",
        equipment_type=EquipmentType.VAV,
        tag="2-18",
        model="Titus TSP",
    )
    vav.measurements = [
        Measurement("design_min", 30, "cfm", Provenance.TECH_ENTERED, technician_confirmed=True),
        Measurement("design_max", 220, "cfm", Provenance.TECH_ENTERED, technician_confirmed=True),
        Measurement("final_max", 305, "cfm", Provenance.TECH_ENTERED, technician_confirmed=True),
    ]

    record.equipment = [rtu, vav]
    record.air_devices = [
        AirDevice("RTU-1", "Outside Air", "Conditioned gym", 2400, 0, 0,
                  "Velocity Grid / Matrix", "N/A", 0, "FAIL",
                  "OA damper observed fully closed"),
        AirDevice("EF-1", "Exhaust Air", "Men's Restroom", 1445, 1445, 1445,
                  "Velocity Grid / Matrix", "25.5x18.25", 556, "MEASURED",
                  "Grid traverse; 556 FPM average"),
        AirDevice("EF-2", "Exhaust Air", "Women's Restroom", 702, 702, 702,
                  "Velocity Grid / Matrix", "25.5x18.25", 270, "MEASURED",
                  "Grid traverse; 270 FPM average"),
    ]
    record.traverses = [
        Traverse(
            traverse_id="TRV-1",
            system_id="OAU-2",
            location="End of catwalk",
            duct_size="18X16",
            area_sqft=2.0,
            design_fpm=1200,
            final_fpm=1108,
            sp="NA",
            points=[
                TraversePoint("A", 1344, 1),
                TraversePoint("B", 1399, 1),
                TraversePoint("C", 906, 1),
                TraversePoint("A", 1034, 2),
                TraversePoint("B", 651, 2),
                TraversePoint("C", 1116, 2),
            ],
        )
    ]
    record.findings = [
        Finding(
            title="OA dampers fully closed on RTU-1",
            detail=(
                "RTU-1 outside air damper observed fully closed; zero "
                "outdoor airflow measured. Correct actuation and re-verify."
            ),
            severity="high",
        )
    ]
    record.environmental_readings = []
    record.photos = []

    if store.exists(metadata.job_id):
        record = store.load(metadata.job_id)
    else:
        store.create(record)

    photos = PhotoIngest(paths).ingest(
        metadata.job_id, _sample_photos(args.photos), classifier=ModelRouter()
    )
    for photo in photos:
        if photo.original_filename not in {p.original_filename for p in record.photos}:
            record.photos.append(photo)
    store.save(record)
    store.save_evidence(metadata.job_id, record.photos)

    plan = plan_for(record)
    store.write_json(metadata.job_id, "plan.json", plan.to_dict())

    composer = Composer(paths, store)
    output = composer.compose(record, plan)
    print(f"OUTPUT_XLSX={output}")

    report = validate_report(
        record, plan, output, masters=MasterStore(paths)
    )
    for check in report.checks:
        print(f"  [{check.status:5s}] {check.name}: {check.message}")
    print(f"VALIDATION={report.summary()}")
    print(f"WORKBOOK_OPENS={'PASS' if not report.blocked else 'FAIL'}")
    return 1 if report.blocked else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scs-reports")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-masters")
    init.add_argument("--source", required=True)
    init.set_defaults(func=cmd_init_masters)

    status = sub.add_parser("masters-status")
    status.set_defaults(func=cmd_masters_status)

    contractors = sub.add_parser("contractors")
    contractors.add_argument("action", choices=("list", "add"))
    contractors.add_argument("--company")
    contractors.add_argument("--contact")
    contractors.add_argument("--email")
    contractors.add_argument("--phone")
    contractors.add_argument("--address")
    contractors.add_argument("--notes")
    contractors.set_defaults(func=cmd_contractors)

    job = sub.add_parser("job")
    job_sub = job.add_subparsers(dest="action", required=True)

    create = job_sub.add_parser("create")
    create.add_argument("--job-id")
    create.add_argument("--project", required=True)
    create.add_argument("--number")
    create.add_argument("--site", required=True)
    create.add_argument("--address")
    create.add_argument("--test-date")
    create.add_argument("--technician", required=True)
    create.add_argument("--contractor")
    create.add_argument("--customer")
    create.add_argument("--engineer")
    create.set_defaults(func=cmd_job_create)

    show = job_sub.add_parser("show")
    show.add_argument("job_id")
    show.set_defaults(func=cmd_job_show)

    add_photo = job_sub.add_parser("add-photo")
    add_photo.add_argument("job_id")
    add_photo.add_argument("files", nargs="+")
    add_photo.set_defaults(func=cmd_job_add_photo)

    add_equipment = job_sub.add_parser("add-equipment")
    add_equipment.add_argument("job_id")
    add_equipment.add_argument("--type", dest="equipment_type", required=True,
                               choices=[t.value for t in EquipmentType])
    add_equipment.add_argument("--tag", required=True)
    add_equipment.add_argument("--manufacturer")
    add_equipment.add_argument("--model")
    add_equipment.add_argument("--serial")
    add_equipment.add_argument("--area")
    add_equipment.add_argument("--notes")
    add_equipment.set_defaults(func=cmd_job_add_equipment)

    add_reading = job_sub.add_parser("add-reading")
    add_reading.add_argument("job_id")
    add_reading.add_argument("equipment")
    add_reading.add_argument("--field", required=True)
    add_reading.add_argument("--value", required=True, type=float)
    add_reading.add_argument("--unit")
    add_reading.set_defaults(func=cmd_job_add_reading)

    add_device = job_sub.add_parser("add-air-device")
    add_device.add_argument("job_id")
    add_device.add_argument("--device", required=True)
    add_device.add_argument("--function", required=True)
    add_device.add_argument("--area")
    add_device.add_argument("--design-cfm", type=float)
    add_device.add_argument("--final-cfm", type=float)
    add_device.add_argument("--method")
    add_device.add_argument("--size")
    add_device.add_argument("--velocity", type=float)
    add_device.add_argument("--status")
    add_device.add_argument("--notes")
    add_device.set_defaults(func=cmd_job_add_air_device)

    add_traverse = job_sub.add_parser("add-traverse")
    add_traverse.add_argument("job_id")
    add_traverse.add_argument("--id", required=True)
    add_traverse.add_argument("--system", required=True)
    add_traverse.add_argument("--location", required=True)
    add_traverse.add_argument("--duct-size", required=True)
    add_traverse.add_argument("--area-sqft", required=True, type=float)
    add_traverse.add_argument("--design-fpm", type=float)
    add_traverse.add_argument("--final-fpm", type=float)
    add_traverse.add_argument("--sp")
    add_traverse.add_argument("--points", nargs="*")
    add_traverse.set_defaults(func=cmd_job_add_traverse)

    add_finding = job_sub.add_parser("add-finding")
    add_finding.add_argument("job_id")
    add_finding.add_argument("--title", required=True)
    add_finding.add_argument("--detail", required=True)
    add_finding.add_argument("--severity", default="info")
    add_finding.set_defaults(func=cmd_job_add_finding)

    notes = job_sub.add_parser("set-notes")
    notes.add_argument("job_id")
    notes.add_argument("--scope")
    notes.add_argument("--observations")
    notes.add_argument("--deficiencies")
    notes.add_argument("--notes")
    notes.set_defaults(func=cmd_job_set_notes)

    plan = job_sub.add_parser("plan")
    plan.add_argument("job_id")
    plan.set_defaults(func=cmd_job_plan)

    compose = job_sub.add_parser("compose")
    compose.add_argument("job_id")
    compose.set_defaults(func=cmd_job_compose)

    validate = job_sub.add_parser("validate")
    validate.add_argument("job_id")
    validate.add_argument("--output")
    validate.set_defaults(func=cmd_job_validate)

    smoke = sub.add_parser("smoke")
    smoke.add_argument("--photos", type=int, default=5)
    smoke.set_defaults(func=cmd_smoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())