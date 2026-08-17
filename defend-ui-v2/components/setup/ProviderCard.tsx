"use client";

import { useState } from "react";
import {
  ProviderView,
  removeSetupSecret,
  saveSetupConfig,
  saveSetupSecret,
  testSetupProvider,
} from "@/lib/setupApi";

const BADGE_LABEL: Record<string, string> = {
  NOT_CONFIGURED: "Not configured",
  NOT_TESTED: "Not tested",
  HEALTHY: "Healthy",
  DEGRADED: "Degraded",
  RATE_LIMITED: "Rate limited",
  UNAVAILABLE: "Unavailable",
  AUTH_FAILED: "Auth failed",
};

const STATE_LABEL: Record<string, string> = {
  DISABLED: "Disabled",
  PLACEHOLDER: "Adapter not implemented",
  AVAILABLE: "Available",
  CONFIGURED: "Configured",
  TESTED: "Tested",
};

type Props = {
  provider: ProviderView;
  token: string;
  onChanged: () => void;
};

export default function ProviderCard({ provider, token, onChanged }: Props) {
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [configValues, setConfigValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(provider.config))
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    kind: "ok" | "err";
    text: string;
  } | null>(null);

  const placeholder = provider.adapter_kind === "placeholder";
  const noCredentials =
    provider.auth_type === "none" || provider.auth_type === "user_agent";

  async function run(action: string, fn: () => Promise<unknown>) {
    setBusy(action);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: "Saved." });
      onChanged();
    } catch (e) {
      setMessage({
        kind: "err",
        text: e instanceof Error ? e.message : "Request failed",
      });
    } finally {
      setBusy(null);
    }
  }

  async function saveSecret(name: string) {
    const value = (secretValues[name] ?? "").trim();
    if (!value) return;
    await run(`save:${name}`, () =>
      saveSetupSecret(token, provider.provider_id, name, value)
    );
    setSecretValues((prev) => ({ ...prev, [name]: "" }));
  }

  async function removeSecret(name: string) {
    await run(`remove:${name}`, () =>
      removeSetupSecret(token, provider.provider_id, name)
    );
  }

  async function saveConfig() {
    await run("config", () =>
      saveSetupConfig(token, provider.provider_id, {
        enabled: provider.enabled,
        config: configValues,
      })
    );
  }

  async function toggleEnabled() {
    await run("enabled", () =>
      saveSetupConfig(token, provider.provider_id, {
        enabled: !provider.enabled,
        config: Object.fromEntries(
          Object.entries(provider.config).filter(([, value]) => value !== "")
        ),
      })
    );
  }

  async function test() {
    setBusy("test");
    setMessage(null);
    try {
      const result = await testSetupProvider(token, provider.provider_id);
      setMessage({
        kind: result.badge === "HEALTHY" ? "ok" : "err",
        text: result.detail ?? result.badge,
      });
      onChanged();
    } catch (e) {
      setMessage({
        kind: "err",
        text: e instanceof Error ? e.message : "Request failed",
      });
    } finally {
      setBusy(null);
    }
  }

  const hasQuota =
    provider.remaining_quota != null ||
    provider.quota_reset_at != null ||
    Object.values(provider.rate_limits).some((value) => value != null);
  const hasLicense = Object.values(provider.license).some(
    (value) => value != null && value !== "unknown"
  );

  return (
    <article className={`setup-card setup-card-${provider.health_badge.toLowerCase()}`}>
      <header className="setup-card-head">
        <div>
          <h3 className="setup-card-title">{provider.display_name}</h3>
          <p className="setup-card-purpose">{provider.purpose}</p>
        </div>
        <span
          className={`setup-pill setup-pill-${provider.state.toLowerCase()}`}
        >
          {STATE_LABEL[provider.state] ?? provider.state}
        </span>
      </header>

      <div className="setup-card-badge">
        <span
          className={`setup-badge setup-badge-${provider.health_badge.toLowerCase()}`}
        >
          {BADGE_LABEL[provider.health_badge] ?? provider.health_badge}
        </span>
        {placeholder && (
          <span className="setup-placeholder">ADAPTER NOT IMPLEMENTED</span>
        )}
      </div>

      {!noCredentials && provider.credentials.length > 0 && (
        <section className="setup-card-creds">
          <h4 className="setup-card-label">Credentials</h4>
          {provider.credentials.map((cred) => (
            <div key={cred.name} className="setup-cred-row">
              <div className="setup-cred-info">
                <span className="setup-cred-name">{cred.name}</span>
                <span className="setup-cred-state">
                  {cred.configured ? cred.masked ?? "configured" : "not set"}
                </span>
              </div>
              <input
                type="password"
                className="setup-input"
                value={secretValues[cred.name] ?? ""}
                onChange={(e) =>
                  setSecretValues((prev) => ({
                    ...prev,
                    [cred.name]: e.target.value,
                  }))
                }
                placeholder={cred.configured ? "Leave blank to keep" : "Enter value"}
                aria-label={`${cred.name} value`}
                disabled={busy !== null || !provider.enabled}
              />
              <div className="setup-cred-actions">
                <button
                  type="button"
                  className="ghost-btn"
                  disabled={
                    busy !== null ||
                    !provider.enabled ||
                    !(secretValues[cred.name] ?? "").trim()
                  }
                  onClick={() => saveSecret(cred.name)}
                >
                  {cred.configured ? "Update" : "Save"}
                </button>
                {cred.configured && (
                  <button
                    type="button"
                    className="setup-remove"
                    disabled={busy !== null}
                    onClick={() => removeSecret(cred.name)}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>
      )}

      {provider.optional_config.length > 0 && (
        <section className="setup-card-creds">
          <h4 className="setup-card-label">Config</h4>
          {provider.optional_config.map((name) => (
            <div key={name} className="setup-cred-row">
              <span className="setup-cred-name">{name}</span>
              <input
                type="text"
                className="setup-input"
                value={configValues[name] ?? ""}
                onChange={(e) =>
                  setConfigValues((prev) => ({
                    ...prev,
                    [name]: e.target.value,
                  }))
                }
                aria-label={`${name} value`}
                disabled={busy !== null || !provider.enabled}
              />
            </div>
          ))}
          <button
            type="button"
            className="ghost-btn"
            disabled={busy !== null || !provider.enabled}
            onClick={saveConfig}
          >
            Save config
          </button>
        </section>
      )}

      {(hasQuota || hasLicense) && (
        <details className="setup-card-details">
          <summary>
            {hasQuota ? "Rate limits & quota" : "License"}
            {hasQuota && hasLicense ? " / " : ""}
            {hasQuota && hasLicense ? "license" : ""}
          </summary>
          <dl className="setup-dl">
            {provider.remaining_quota != null && (
              <div>
                <dt>Remaining quota</dt>
                <dd>{provider.remaining_quota}</dd>
              </div>
            )}
            {provider.quota_reset_at != null && (
              <div>
                <dt>Quota resets</dt>
                <dd>{provider.quota_reset_at}</dd>
              </div>
            )}
            {Object.entries(provider.rate_limits)
              .filter(([, value]) => value != null)
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replace(/_/g, " ")}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            {provider.license.terms_url && (
              <div>
                <dt>Terms</dt>
                <dd>
                  <a href={provider.license.terms_url} target="_blank" rel="noreferrer">
                    {provider.license.terms_url}
                  </a>
                </dd>
              </div>
            )}
            {provider.license.commercial_use_status !== "unknown" && (
              <div>
                <dt>Commercial use</dt>
                <dd>{provider.license.commercial_use_status}</dd>
              </div>
            )}
            {provider.license.redistribution_status !== "unknown" && (
              <div>
                <dt>Redistribution</dt>
                <dd>{provider.license.redistribution_status}</dd>
              </div>
            )}
            {provider.license.attribution_requirement && (
              <div>
                <dt>Attribution</dt>
                <dd>{provider.license.attribution_requirement}</dd>
              </div>
            )}
          </dl>
        </details>
      )}

      <footer className="setup-card-foot">
        <label className="setup-enable">
          <input
            type="checkbox"
            checked={provider.enabled}
            onChange={toggleEnabled}
            disabled={busy !== null}
            aria-label={`Enable ${provider.display_name}`}
          />
          Enabled
        </label>
        <div className="setup-card-meta">
          {provider.last_latency_ms != null && (
            <span className="setup-meta">{provider.last_latency_ms} ms</span>
          )}
          {provider.tested_at != null && (
            <span className="setup-meta">{provider.tested_at}</span>
          )}
          {provider.last_success_at != null && (
            <span className="setup-meta">
              last ok {provider.last_success_at}
            </span>
          )}
        </div>
        <button
          type="button"
          className="setup-test"
          disabled={busy !== null || !provider.enabled || placeholder}
          title={placeholder ? "ADAPTER NOT IMPLEMENTED" : "Run health test"}
          onClick={test}
        >
          {busy === "test" ? "Testing…" : "Test"}
        </button>
      </footer>

      {message && (
        <p
          role={message.kind === "err" ? "alert" : "status"}
          className={
            message.kind === "err" ? "setup-msg-err" : "setup-msg-ok"
          }
        >
          {message.text}
        </p>
      )}
    </article>
  );
}