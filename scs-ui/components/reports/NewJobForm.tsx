"use client";

import { FormEvent, useEffect, useState } from "react";
import { addContractor, createJob, listContractors } from "@/lib/reportsApi";
import type { Contractor, JobRecord } from "@/lib/reportTypes";

export function NewJobForm({
  defaultTechnician,
  onCreated,
  onCancel,
}: {
  defaultTechnician: string;
  onCreated: (record: JobRecord) => void;
  onCancel: () => void;
}) {
  const [contractors, setContractors] = useState<Contractor[]>([]);
  const [addingContractor, setAddingContractor] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState({
    project_name: "",
    project_number: "",
    site_name: "",
    site_address: "",
    test_date: new Date().toISOString().slice(0, 10),
    technician: defaultTechnician,
    hiring_contractor: "",
  });

  useEffect(() => {
    listContractors()
      .then((payload) => setContractors(payload.contractors))
      .catch(() => setContractors([]));
  }, []);

  function setField(field: string, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
  }

  async function saveContractor(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await addContractor({
        name: companyName.trim(),
        contact: contact.trim() || null,
        phone: phone.trim() || null,
        email: email.trim() || null,
      });
      setContractors((current) => [...current, created]);
      setValues((current) => ({ ...current, hiring_contractor: created.company_name }));
      setAddingContractor(false);
      setCompanyName("");
      setContact("");
      setPhone("");
      setEmail("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add contractor");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!values.project_name.trim() || !values.project_number.trim()) {
      setError("Project name and project number are required.");
      return;
    }
    setBusy(true);
    try {
      const record = await createJob({
        ...values,
        hiring_contractor: values.hiring_contractor || null,
      });
      onCreated(record);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create job");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="reports-form" onSubmit={submit}>
      <div className="reports-grid-two">
        <label>
          Project name *
          <input
            value={values.project_name}
            onChange={(e) => setField("project_name", e.target.value)}
            placeholder="e.g. Crunch Fitness Lakeland"
          />
        </label>
        <label>
          Project number *
          <input
            value={values.project_number}
            onChange={(e) => setField("project_number", e.target.value)}
            placeholder="e.g. 2026-0147"
          />
        </label>
        <label>
          Site name
          <input
            value={values.site_name}
            onChange={(e) => setField("site_name", e.target.value)}
            placeholder="e.g. Lakeland"
          />
        </label>
        <label>
          Site address
          <input
            value={values.site_address}
            onChange={(e) => setField("site_address", e.target.value)}
            placeholder="Street, city"
          />
        </label>
        <label>
          Test date
          <input
            type="date"
            value={values.test_date}
            onChange={(e) => setField("test_date", e.target.value)}
          />
        </label>
        <label>
          Technician
          <input
            value={values.technician}
            onChange={(e) => setField("technician", e.target.value)}
          />
        </label>
        <label>
          Hiring contractor
          <select
            value={values.hiring_contractor}
            onChange={(e) => setField("hiring_contractor", e.target.value)}
          >
            <option value="">— select or add —</option>
            {contractors.map((contractor) => (
              <option key={contractor.company_name} value={contractor.company_name}>
                {contractor.company_name}
              </option>
            ))}
          </select>
        </label>
        <div className="reports-add-contractor-toggle">
          <button
            type="button"
            className="button-link"
            onClick={() => setAddingContractor((current) => !current)}
          >
            {addingContractor ? "Cancel add contractor" : "+ Add contractor"}
          </button>
        </div>
      </div>
      {addingContractor && (
        <div className="reports-subform">
          <h4>Add contractor</h4>
          <div className="reports-grid-two">
            <label>
              Company name *
              <input
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="Company"
              />
            </label>
            <label>
              Contact
              <input
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                placeholder="Name"
              />
            </label>
            <label>
              Phone
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="(000) 000-0000"
              />
            </label>
            <label>
              Email
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
              />
            </label>
          </div>
          <button type="button" className="button-secondary" onClick={saveContractor} disabled={busy || !companyName.trim()}>
            {busy ? "Saving…" : "Save contractor"}
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="login-error">
          {error}
        </p>
      )}
      <div className="reports-actions">
        <button type="submit" className="button-primary" disabled={busy}>
          {busy ? "Creating…" : "Create job"}
        </button>
        <button type="button" className="button-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}