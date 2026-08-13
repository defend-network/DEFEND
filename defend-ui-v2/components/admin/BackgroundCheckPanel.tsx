"use client";

const actions = [
  ["New background check", "Open a permissioned screening case."],
  ["Person search", "Search verified public and authorized person sources."],
  ["Business search", "Review organizations, ownership, and registrations."],
  ["Court records", "Collect jurisdiction-aware public court records."],
  ["Sanctions / watchlists", "Check official sanctions and watchlist sources."],
  ["Web research", "Run sourced open-web research for the case."],
  ["Social media search", "Review attributable public social profiles."],
  ["Voter status", "Check lawful public registration status where permitted."],
  ["Saved cases", "Resume prior screening cases and review their audit history."],
  ["Generate report", "Create a sourced report for human review."],
] as const;

export function BackgroundCheckPanel() {
  return (
    <>
      <div className="page-heading">
        <span className="eyebrow">Screening workspace</span>
        <h1>Background Check</h1>
        <p>
          Future investigative workflows will collect attributable sources into
          a permissioned case without making automatic eligibility decisions.
        </p>
      </div>

      <section className="admin-card background-check-principles">
        <div>
          <span className="eyebrow">Record architecture</span>
          <strong>One canonical Person record</strong>
          <p className="muted">
            A screening case can later link to the same Applicant and Member
            lifecycle, preserving status, notes, documents, and history.
          </p>
        </div>
        <div>
          <span className="eyebrow">Decision boundary</span>
          <strong>Evidence for human review</strong>
          <p className="muted">
            DEFEND will summarize sourced evidence; authorized people remain
            responsible for membership and disciplinary decisions.
          </p>
        </div>
      </section>

      <section className="background-check-grid" aria-label="Background check actions">
        {actions.map(([name, description]) => (
          <article className="admin-card background-check-action" key={name}>
            <span className="tool-chip">Planned</span>
            <h2>{name}</h2>
            <p className="muted">{description}</p>
            <button type="button" className="ghost-btn" disabled aria-label={name}>
              Coming soon
            </button>
          </article>
        ))}
      </section>

      <section className="admin-card">
        <div className="card-title">Privacy and audit controls</div>
        <p className="muted">
          Future searches must enforce role and field permissions, legal-purpose
          restrictions, source attribution, append-only access auditing,
          retention rules, and explicit handling of sensitive records.
        </p>
      </section>
    </>
  );
}
