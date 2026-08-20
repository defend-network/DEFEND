"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { JobRecord } from "@/lib/reportTypes";
import { SECTION_GROUPS, SECTION_TITLES } from "@/lib/reportTypes";
import { sectionReason } from "@/lib/reportStatus";
import { getPlan } from "@/lib/reportsApi";

export function PlanPanel({
  record,
  commit,
  planSections,
  setPlanSections,
}: {
  record: JobRecord;
  commit: (record: JobRecord) => void;
  planSections: string[] | null;
  setPlanSections: Dispatch<SetStateAction<string[] | null>>;
}) {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPlan(record.metadata.job_id)
      .then((payload) => {
        setPlanSections(payload.sections);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [record.metadata.job_id, setPlanSections]);

  const overridden = new Set(
    record.plan_overrides
      .filter((entry) => entry.startsWith("remove:"))
      .map((entry) => entry.slice("remove:".length)),
  );
  const added = new Set(
    record.plan_overrides
      .filter((entry) => entry.startsWith("add:"))
      .map((entry) => entry.slice("add:".length)),
  );

  function toggleOverride(section: string, action: "add" | "remove") {
    const entry = `${action}:${section}`;
    const inverse = `${action === "add" ? "remove" : "add"}:${section}`;
    const overrides = record.plan_overrides
      .filter((item) => item !== entry && item !== inverse)
      .concat(record.plan_overrides.includes(entry) ? [] : [entry]);
    commit({ ...record, plan_overrides: overrides });
    setPlanSections((current) => {
      if (!current) {
        return current;
      }
      if (action === "remove") {
        return current.filter((item) => item !== section);
      }
      return current.includes(section) ? current : [...current, section];
    });
  }

  if (loading) {
    return <p className="chat-placeholder">Planning…</p>;
  }

  const included = planSections ?? [];
  const allSections = Object.keys(SECTION_TITLES);
  const excluded = allSections.filter((section) => !included.includes(section));
  const grouped = (sections: string[]) =>
    Object.entries(
      sections.reduce<Record<string, string[]>>((groups, section) => {
        const group = SECTION_GROUPS[section] ?? "Other";
        groups[group] = [...(groups[group] ?? []), section];
        return groups;
      }, {}),
    );

  return (
    <section className="reports-panel">
      <h4>Report plan</h4>
      <p className="muted">
        Sections are chosen from the job content. Overrides are allowed and recorded as manual.
      </p>
      <h5>Included</h5>
      {grouped(included).map(([group, sections]) => (
        <div key={group}>
          <h6 className="reports-group-label">{group}</h6>
          <ul className="reports-plan-list">
            {sections.map((section) => (
              <li key={section}>
                <div>
                  <strong>{SECTION_TITLES[section]}</strong>
                  <p className="muted">{sectionReason(section, record.plan_overrides)}</p>
                  {(overridden.has(section) || added.has(section)) && (
                    <span className="pill pill-warn">manual override</span>
                  )}
                </div>
                <button className="button-link" onClick={() => toggleOverride(section, "remove")}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
      <h5>Excluded</h5>
      {grouped(excluded).map(([group, sections]) => (
        <div key={group}>
          <h6 className="reports-group-label">{group}</h6>
          <ul className="reports-plan-list">
            {sections.map((section) => (
              <li key={section}>
                <div>
                  <strong>{SECTION_TITLES[section]}</strong>
                  <p className="muted">
                    {overridden.has(section)
                      ? sectionReason(section, record.plan_overrides)
                      : "No job content for this section"}
                  </p>
                </div>
                {!["cover", "certification", "closeout"].includes(section) && (
                  <button className="button-link" onClick={() => toggleOverride(section, "add")}>
                    Add
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}