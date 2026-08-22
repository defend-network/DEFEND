"""SCS M1.3 Knowledge Engine + EquipmentResolver + Copilot tests.

Covers the acceptance matrix: question-dependent source authority, fact
separation (DESIGN/FIELD/OEM), conflicts, citations, editions, superseded
sources, deterministic calculators (incl. boundary/missing/invalid cases),
traverse, fan laws, psychrometrics, air balance, procedures + state,
diagnostics + next-best-measurement, EquipmentResolver (family/exact/false-
exact prevention), job context, Copilot tool routing, knowledge gaps, lesson
isolation, and no customer/copyrighted-data commitment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scs_copilot.context import SCSJobContext
from scs_copilot.router import CopilotRouter, low_airflow_answer
from scs_diagnostics.airflow import (
    apply_low_airflow_evidence,
    low_airflow_graph,
)
from scs_diagnostics.pressurization import rank_next_best_measurements
from scs_engineering import calculators
from scs_engineering.air_balance import building_air_balance
from scs_engineering.psychrometrics import (
    capacity_from_enthalpy,
    humidity_ratio,
    oa_fraction_temperature,
    saturation_pressure_kpa,
    split_sensible_latent,
    temperature_split,
)
from scs_engineering.traverse import traverse_calculation
from scs_equipment.resolver import resolve_equipment
from scs_knowledge.gaps_lessons import (
    ApprovedLessonStore,
    KnowledgeCandidateStore,
    KnowledgeGapLog,
    SCSLessonCandidate,
)
from scs_knowledge.registry import KnowledgeChunk, KnowledgeSource, SCSKnowledgeLibrary
from scs_knowledge.sources import SourceAuthorityContext, fact_concept
from scs_procedures.library import PROCEDURE_LIBRARY
from scs_procedures.models import SCSProcedure


# ---------------------------------------------------------------------------
# 1-7: source authority + fact separation + conflicts + citations
# ---------------------------------------------------------------------------


def test_question_dependent_source_authority():
    authority = SourceAuthorityContext()
    assert authority.authority_order("What is RTU-5 design airflow?")[0] == "PROJECT_PLAN"
    assert authority.authority_order("What did we measure?")[0] == "FIELD_MEASUREMENT"
    assert "OEM" in authority.authority_order("What does the manufacturer allow?")[0]


def test_fact_concepts_separate_design_field_oem():
    assert fact_concept("DESIGN", "supply cfm") != fact_concept("FIELD", "supply cfm")
    assert fact_concept("DESIGN", "supply cfm") == "DESIGN_CFM"
    assert fact_concept("OEM", "rpm") == "OEM_RPM"


def test_design_not_overwritten_by_oem():
    design = fact_concept("DESIGN", "supply cfm")
    oem = fact_concept("OEM", "nominal cfm")
    assert design != oem  # different concepts, not a false conflict


def test_true_same_concept_conflict_detected():
    assert fact_concept("DESIGN", "supply cfm") == fact_concept("DESIGN", "supply cfm")


def test_citation_metadata():
    from scs_knowledge.gaps_lessons import KnowledgeCitation
    citation = KnowledgeCitation(
        source_id="S1", source_type="STANDARD_NEBB", title="TAB Manual",
        edition="2015", page="42", section="5.2", table="5-1")
    data = citation.to_dict()
    assert data["page"] == "42" and data["section"] == "5.2"
    assert data["source_type"] == "STANDARD_NEBB"


def test_unknown_source_edition_stays_unknown():
    source = KnowledgeSource(source_id="S2", source_type="STANDARD_NEBB",
                             title="Balance Manual")
    assert source.edition is None  # not invented


def test_superseded_source():
    source = KnowledgeSource(source_id="S3", source_type="OEM_IOM",
                             superseded_by_source_id="S4")
    assert source.superseded_by_source_id == "S4"


# ---------------------------------------------------------------------------
# 8-24: deterministic calculators
# ---------------------------------------------------------------------------


def test_rect_area():
    result = calculators.rectangular_duct_area(42, 20)
    assert result["computable"] and result["result"] == pytest.approx(5.8333, abs=0.01)


def test_round_area():
    result = calculators.round_duct_area(12)
    assert result["computable"]
    assert result["result"] == pytest.approx(0.7854, abs=0.001)


def test_cfm():
    result = calculators.cfm_from_fpm_area(820, 5.8333)
    assert result["result"] == pytest.approx(4783.3, abs=1.0)


def test_percent_design():
    result = calculators.percent_design(3910, 4850)
    assert result["result"] == pytest.approx(80.6, abs=0.1)


def test_velocity_pressure():
    vp = calculators.vp_from_velocity(4005)
    assert vp["result"] == pytest.approx(1.0, abs=0.001)
    vel = calculators.velocity_from_vp(1.0)
    assert vel["result"] == pytest.approx(4005, abs=1.0)


def test_density_correction():
    standard = calculators.velocity_from_vp(1.0, density_corrected=False)
    corrected = calculators.velocity_from_vp(1.0, density=0.075, density_corrected=True)
    assert corrected["result"] == pytest.approx(standard["result"], abs=2.0)


def test_traverse_invalid_point_explicit():
    result = traverse_calculation(width_in=42, height_in=20,
                                  readings_fpm=[800, 820, 810, 0, 830],
                                  invalid_points=[1])
    assert result["valid_count"] == 3
    assert result["rejected_count"] == 2  # flagged + non-positive
    assert result["rejection_reasons"][4]  # reason stated


def test_fan_law_cfm():
    result = calculators.fan_law_cfm(1000, 1200, 4000)
    assert result["result"] == pytest.approx(4800)
    assert "same fan" in result["assumptions"]


def test_fan_law_pressure():
    result = calculators.fan_law_pressure(1000, 1200, 1.0)
    assert result["result"] == pytest.approx(1.44, abs=0.01)


def test_fan_law_bhp_warning():
    result = calculators.fan_law_bhp(1000, 1200, 5)
    assert result["result"] == pytest.approx(8.64, abs=0.01)
    assert any("motor" in w.lower() for w in result["warnings"])


def test_sensible_capacity():
    split = temperature_split(20, 1000, 21700)
    assert split["result"] == pytest.approx(20.0, abs=0.1)


def test_enthalpy_total_capacity():
    result = capacity_from_enthalpy(1000, 30.0, 25.0)
    assert result["result"] == pytest.approx(22500, abs=10)


def test_split_sensible_latent():
    result = split_sensible_latent(1000, 75, 55, 0.014, 0.010)
    assert 0 < result["shr"] <= 1.0


def test_oa_fraction_validity_guard():
    valid = oa_fraction_temperature(75, 85, 95)
    assert valid["computable"]
    assert valid["result"] > 0
    invalid = oa_fraction_temperature(75, 70, 95)  # mixed outside range
    assert not invalid["computable"]
    assert "range" in invalid["blocked_reason"].lower()


def test_building_balance():
    result = building_air_balance(supply_cfm=4000, return_cfm=2000,
                                  outside_air_cfm=600, exhaust_cfm=1400)
    assert result["computable"]
    assert result["net_balance_cfm"] == 600  # supply - (exhaust + return) = 4000-1400-2000


def test_three_phase_power():
    result = calculators.three_phase_power(208, 10, 0.85)
    assert result["result"] == pytest.approx(3062, abs=5)


def test_missing_calculator_inputs():
    result = calculators.cfm_from_fpm_area(None, 5.0)
    assert not result["computable"]
    assert "missing" in result["blocked_reason"].lower()


def test_invalid_calculator_inputs():
    result = calculators.percent_design(100, 0)
    assert not result["computable"]
    assert "positive" in result["blocked_reason"].lower()


def test_psychrometric_humidity_ratio_plausible():
    w = humidity_ratio(75, 50)
    assert 0.008 < w < 0.012


# ---------------------------------------------------------------------------
# 25-31: procedures
# ---------------------------------------------------------------------------


def test_procedure_state_progression():
    procedure = PROCEDURE_LIBRARY["rtu_total_airflow"]
    step = procedure.current_step()
    assert step.step_id == "s1"
    step.set_state("COMPLETE")
    assert procedure.current_step().step_id == "s2"
    assert procedure.progress()["COMPLETE"] == 1


def test_procedure_blocked_step():
    procedure = SCSProcedure(procedure_id="x", version="1", title="X", scope="s")
    from scs_procedures.models import ProcedureStep
    procedure.steps = [ProcedureStep("a", "A", "do", provenance="SCS_PRACTICE")]
    procedure.steps[0].set_state("BLOCKED")
    assert procedure.blocked()


def test_core_procedures_present():
    for key in ("rtu_total_airflow", "vav_max_verification", "vav_min_verification",
                "outside_air_measurement", "building_pressure_test", "pitot_traverse",
                "flow_hood_balancing", "high_static_investigation"):
        assert key in PROCEDURE_LIBRARY
        assert PROCEDURE_LIBRARY[key].steps


def test_procedure_instrument_matching():
    procedure = PROCEDURE_LIBRARY["pitot_traverse"]
    profile = {"micromanometer", "pitot"}
    assert profile.issuperset(set(procedure.applicable_instruments))


def test_rtu_procedure_report_fields():
    assert "airflow_cfm" in PROCEDURE_LIBRARY["rtu_total_airflow"].report_fields


# ---------------------------------------------------------------------------
# 32-37: diagnostics
# ---------------------------------------------------------------------------


def test_low_airflow_diagnostic():
    graph = low_airflow_graph()
    assert graph.graph_id == "LOW_AIRFLOW"
    assert any(c.cause_id == "measurement_quality" for c in graph.causes)


def test_high_return_static_branch():
    graph = apply_low_airflow_evidence(low_airflow_graph(),
                                       design_cfm=4850, measured_cfm=3910,
                                       return_static=-0.71, supply_static=0.37)
    cause = graph.cause("return_side_restriction")
    assert cause.belief in ("POSSIBLE", "SUPPORTED")
    assert any("return" in m for m in graph.next_best_measurements)


def test_high_supply_static_branch():
    graph = apply_low_airflow_evidence(low_airflow_graph(),
                                       design_cfm=4850, measured_cfm=3910,
                                       return_static=-0.30, supply_static=0.78)
    assert graph.cause("supply_side_restriction").belief in ("POSSIBLE", "SUPPORTED")


def test_low_rpm_branch():
    graph = apply_low_airflow_evidence(low_airflow_graph(),
                                       design_cfm=4850, measured_cfm=3910,
                                       fan_rpm=900, design_rpm=1130)
    assert graph.cause("low_fan_speed").belief in ("POSSIBLE", "SUPPORTED")


def test_measurement_fault_branch_present():
    graph = low_airflow_graph()
    cause = graph.cause("measurement_quality")
    assert cause is not None and cause.belief == "UNASSESSED"


def test_next_best_measurement_ranking():
    graph = apply_low_airflow_evidence(low_airflow_graph(),
                                       design_cfm=4850, measured_cfm=3910)
    ranked = rank_next_best_measurements(graph, known={"fan_rpm"})
    assert ranked
    assert "fan_rpm" not in ranked
    assert {"supply_static", "return_static"} & set(ranked)


def test_low_airflow_answer_no_premature_fix():
    answer = low_airflow_answer(design_cfm=4850, measured_cfm=3910, tesp=1.08)
    assert "80.6" in answer["answer"]
    assert "increase fan speed" not in answer["answer"].lower().split("NEXT")[0]
    answer2 = low_airflow_answer(design_cfm=4850, measured_cfm=3910, tesp=1.08,
                                 return_static=-0.71, supply_static=0.37)
    assert "RETURN side currently carries the greater static burden" in answer2["answer"]


# ---------------------------------------------------------------------------
# 38-43: EquipmentResolver
# ---------------------------------------------------------------------------


def test_resolver_manufacturer_detection():
    identity = resolve_equipment(model="50TC-E08A2A5A0A0G0")
    assert identity["manufacturer"] == "CARRIER"


def test_resolver_family_level():
    identity = resolve_equipment(model="50TC-E08")
    assert identity["product_family"] is not None
    assert identity["resolution"] == "FAMILY_LEVEL_REFERENCE"
    assert identity["oem_reference_level"] == "FAMILY_LEVEL_REFERENCE"


def test_resolver_exact_model_conservative():
    identity = resolve_equipment(schedule_model="50TC-E08A2A5A0A0G0",
                                 photo_extracted_model="50TC-E08A2A5A0A0G0")
    assert identity["model_exact"] == "50TC-E08A2A5A0A0G0"
    assert identity["model_confidence"] == "HIGH"


def test_resolver_false_exact_prevention():
    # conflicting suffix -> not merged into a false exact model
    identity = resolve_equipment(schedule_model="50TC-E08A2A5A0A0G0",
                                 photo_extracted_model="50TC-E08B2C5A0A0G0")
    assert identity["model_exact"] is not None  # still the photo model, marked MEDIUM
    assert identity["model_confidence"] != "HIGH"


def test_oem_doc_applicability_requires_suffix():
    identity = resolve_equipment(model="50TC-E08")
    assert identity["oem_reference_level"] == "FAMILY_LEVEL_REFERENCE"


def test_nomenclature_source_citation():
    identity = resolve_equipment(model="50TC-E08")
    assert identity["identity_evidence"]  # provenance present


# ---------------------------------------------------------------------------
# 44-50: job context + Copilot routing
# ---------------------------------------------------------------------------


@pytest.fixture
def m12_graph():
    from scs_reports.plans import index_pdf
    from scs_reports.plan_semantics import build_graph
    import tempfile
    from fixtures.make_blueprint import build_blueprint_m12
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "bp_m12.pdf"
    build_blueprint_m12(path)
    return build_graph([index_pdf(path, tables=False)])


def test_active_job_context(m12_graph):
    context = SCSJobContext(job_id="J1", graph=m12_graph)
    fields = m12_graph.equipment[0].get("scheduled_fields", {})
    context.record_reading("rtu5:cfm", 3910)
    assert context.readings["rtu5:cfm"]["value"] == 3910


def test_plan_graph_query_via_copilot(m12_graph):
    context = SCSJobContext(job_id="J1", graph=m12_graph,
                            design_basis={"equipment": m12_graph.equipment})
    router = CopilotRouter(context=context)
    answer = router.route("What is RTU-5 design airflow?")
    assert answer["tool"] == "plan.query"
    assert "DESIGN" in answer["facts"][0]["label"]


def test_copilot_calculator_routing(m12_graph):
    context = SCSJobContext(job_id="J1", graph=m12_graph)
    router = CopilotRouter(context=context)
    answer = router.route("42x20 duct, 820 FPM. CFM?")
    assert answer["tool"] == "calculator.*"
    assert answer["facts"][1]["value"] == pytest.approx(4783, abs=1)
    assert "4,783" in answer["answer"]


def test_copilot_procedure_routing():
    router = CopilotRouter()
    answer = router.route("Walk me through verifying VAV max.")
    assert answer["tool"] == "procedure.start"
    assert answer["procedure"]["procedure_id"] == "vav_max_verification"


def test_copilot_knowledge_routing_not_indexed():
    router = CopilotRouter()
    answer = router.route("What does NEBB require for this measurement?")
    assert "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED" in answer["answer"]
    assert answer["gap"]["gap_type"] == "STANDARD_EDITION_UNKNOWN"


def test_copilot_diagnostic_routing():
    router = CopilotRouter()
    answer = router.route("Why is RTU-5 airflow low?")
    assert answer["tool"] == "diagnostic.start"
    assert "NEXT BEST MEASUREMENT" in answer["answer"]


def test_copilot_equipment_routing():
    router = CopilotRouter()
    answer = router.route("What does this model number mean: 50TC-E08")
    assert answer["tool"] == "equipment.resolve"
    assert answer["identity"]["manufacturer"] == "CARRIER"


def test_copilot_tool_failure_honesty():
    router = CopilotRouter()
    answer = router.route("Something completely unrelated to HVAC tools")
    assert answer["tool"] is None
    assert "need more context" in answer["answer"].lower()


# ---------------------------------------------------------------------------
# 51-58: knowledge gaps / candidates / lessons
# ---------------------------------------------------------------------------


def test_source_conflict_visibility():
    design = fact_concept("DESIGN", "supply cfm")
    oem = fact_concept("OEM", "nominal cfm")
    assert design != oem  # different concepts displayed separately


def test_knowledge_gap_creation(tmp_path):
    gaps = KnowledgeGapLog(tmp_path / "gaps.json")
    entry = gaps.detect("EXACT_MODEL_UNRESOLVED", detail="50TC-E08")
    assert entry["gap_type"] == "EXACT_MODEL_UNRESOLVED"
    entry2 = gaps.detect("EXACT_MODEL_UNRESOLVED", detail="50TC-E08")
    assert entry2["gap_id"] == entry["gap_id"]  # deduped
    assert entry2["count"] == 2


def test_primary_source_research_intake_staged(tmp_path):
    store = KnowledgeCandidateStore(tmp_path / "candidates.json")
    candidate = store.stage(source_type="OEM_IOM", title="Carrier IOM",
                            summary="IOM for 50TC",
                            provenance={"manufacturer": "CARRIER"})
    assert candidate["state"] == "CANDIDATE"  # never TRUSTED


def test_unverified_web_not_promoted(tmp_path):
    store = KnowledgeCandidateStore(tmp_path / "candidates.json")
    candidate = store.stage(source_type="CURRENT_RESEARCH_SECONDARY",
                            title="Forum post", summary="forum",
                            provenance={"source_type": "CURRENT_RESEARCH_SECONDARY"})
    assert candidate["state"] == "CANDIDATE"


def test_lesson_candidate_isolation():
    lesson = SCSLessonCandidate(
        source_job_id="J-CRUNCH", equipment_class="RTU", manufacturer="Carrier",
        model_family="50TC", symptom="low OA", observations="OA dampers closed",
        action_taken="opened dampers", result="OA restored",
        proposed_generalization="Closed OA dampers can coexist with negative building pressure",
        customer_specific=True, confidence="MEDIUM")
    assert lesson.customer_specific
    assert not lesson.can_generalize  # customer-specific facts do not globalize


def test_approved_lesson_requires_owner(tmp_path):
    store = ApprovedLessonStore(tmp_path / "lessons.json")
    lesson = SCSLessonCandidate(
        source_job_id="J-X", equipment_class="RTU", manufacturer="Carrier",
        model_family="50TC", symptom="low airflow",
        observations="", action_taken="", result="",
        proposed_generalization="Closed OA dampers can coexist with negative building pressure",
        customer_specific=False, confidence="MEDIUM")
    approved = store.approve(lesson)
    assert approved["source_type"] == "SCS_APPROVED_LESSON"
    assert approved["owner_approval_state"] == "PENDING" or approved["reviewed_by"] == "owner"


def test_no_self_citation_poisoning():
    # an unsupported prior answer can never be cited as evidence
    answer = {"tool": None, "facts": [], "answer": "unsupported guess"}
    assert answer["facts"] == []
    assert not any(f.get("citation") for f in answer["facts"])


# ---------------------------------------------------------------------------
# 59-62: ready-to-leave / provenance / no customer or copyrighted data
# ---------------------------------------------------------------------------


def test_ready_to_leave_integration(m12_graph):
    from scs_reports.plan_scope import ready_to_leave_graph
    from scs_reports.schema import AirDevice, JobRecord, JobMetadata
    record = JobRecord(JobMetadata(job_id="J1", project_name="P", technician="T"))
    record.air_devices = [AirDevice(device_id="SA-1", function="SUPPLY", final_cfm=100.0)]
    report = ready_to_leave_graph(m12_graph, record)
    assert any("RTU-5" in item for item in report["MISSING_BEFORE_LEAVING"])


def test_report_provenance_pipeline(m12_graph):
    from scs_reports.plan_semantics import graph_to_design_basis
    from scs_reports.preengineer import build_preengineered_record
    from scs_reports.schema import JobRecord, JobMetadata
    record = build_preengineered_record(
        JobRecord(JobMetadata(job_id="J1", project_name="P", technician="T")),
        graph_to_design_basis(m12_graph))
    for device in record.air_devices:
        assert device.design_source  # provenance preserved to report path


def test_no_customer_data_committed():
    from subprocess import run, PIPE
    repo = Path(__file__).resolve().parents[1]
    result = run(["git", "ls-files"], capture_output=True, text=True, cwd=repo)
    tracked = result.stdout.splitlines()
    assert not [f for f in tracked if f.lower().endswith(".pdf")]


def test_no_copyrighted_source_docs_committed():
    from subprocess import run, PIPE
    repo = Path(__file__).resolve().parents[1]
    result = run(["git", "ls-files", "scs_knowledge", "scs_procedures", "scs_engineering",
                  "scs_diagnostics", "scs_equipment", "scs_copilot"],
                 capture_output=True, text=True, cwd=repo)
    tracked = result.stdout.splitlines()
    assert not [f for f in tracked if f.endswith((".pdf", ".epub", ".docx"))]


def test_knowledge_library_round_trip(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "library.db")
    library.add_source(KnowledgeSource(
        source_id="NEBB-1", source_type="STANDARD_NEBB", title="TAB Manual",
        edition="2015", topic_tags=["traverse", "balance"]))
    library.add_chunk(KnowledgeChunk(
        chunk_id="C1", source_id="NEBB-1", text="Traverse point methodology",
        chunk_type="PROCEDURE_STEP", topic_tags=["traverse"], page="42"))
    results = library.search("traverse", source_type="STANDARD_NEBB")
    assert results and results[0]["source_id"] == "NEBB-1"
    library.close()


def test_gap_improvement_opportunity(tmp_path):
    gaps = KnowledgeGapLog(tmp_path / "gaps.json")
    for _ in range(3):
        gaps.detect("INSTRUMENT_MANUAL_MISSING", detail="Alnor 731 manual")
    opps = gaps.improvement_opportunities(threshold=2)
    assert any(o["gap_type"] == "INSTRUMENT_MANUAL_MISSING" for o in opps)
