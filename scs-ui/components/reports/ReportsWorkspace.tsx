"use client";

import { useState } from "react";
import { ReportsHome } from "./ReportsHome";
import { JobFlow } from "./JobFlow";

export function ReportsWorkspace({ technician }: { technician: string }) {
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  return (
    <section id="reports" className="reports-section">
      <div className="section-title">
        <div>
          <p className="eyebrow">Field reports</p>
          <h2>Reports</h2>
        </div>
        <span>TAB workflow: create → evidence → plan → validate → export</span>
      </div>
      {openJobId ? (
        <JobFlow jobId={openJobId} onBack={() => setOpenJobId(null)} />
      ) : (
        <ReportsHome defaultTechnician={technician} onOpen={setOpenJobId} />
      )}
    </section>
  );
}