"use client";

import { ModelTargetPublic, RunRouting } from "@/app/workspace/load-workspace";

export type ModelMode = "AUTO" | "DEEPSEEK" | "NEXT" | "SOL";

const MODE_LABELS: Record<ModelMode, string> = {
  AUTO: "Auto — recommended",
  DEEPSEEK: "DeepSeek V4 Flash",
  NEXT: "Next · Heavy",
  SOL: "GPT-5.6 Sol",
};

type Props = {
  mode: ModelMode;
  currentModel: string;
  routing: RunRouting | null;
  targets: Record<string, ModelTargetPublic> | null;
  role: "admin" | "consumer";
  disabled: boolean;
  onChange: (mode: ModelMode) => void;
};

export default function ModelSelector({
  mode,
  currentModel,
  routing,
  targets,
  role,
  disabled,
  onChange,
}: Props) {
  const solAvailable = targets?.["gpt-5.6-sol"]?.available ?? false;
  const deepseekAvailable =
    targets?.["deepseek-v4-flash"]?.available ?? false;
  const nextAvailable = targets?.["Qwen/Qwen3-Coder-Next"]?.available ?? true;

  return (
    <div className="model-selector" aria-label="Model selection">
      <div className="model-mode-row">
        <span className="runtime-label">Mode</span>
        <select
          aria-label="Model mode"
          value={mode}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as ModelMode)}
        >
          <option value="AUTO">{MODE_LABELS.AUTO}</option>
          <option value="DEEPSEEK" disabled={!deepseekAvailable}>
            {MODE_LABELS.DEEPSEEK}
            {!deepseekAvailable ? " · not configured" : ""}
          </option>
          <option value="NEXT" disabled={role !== "admin" || !nextAvailable}>
            {MODE_LABELS.NEXT}
            {role !== "admin" ? " (owner only)" : ""}
          </option>
          <option value="SOL" disabled={role !== "admin" || !solAvailable}>
            {MODE_LABELS.SOL}
            {!solAvailable ? " · not configured" : role !== "admin" ? " (owner only)" : ""}
          </option>
        </select>
      </div>
      <div className="model-current-row">
        <span className="runtime-label">Current</span>
        <strong>{currentModel || "—"}</strong>
      </div>
      {routing && routing.requested_mode === "AUTO" && routing.selected_model !== "deepseek" ? (
        <div className="model-escalated-hint">
          Mode: AUTO · Current: {routing.selected_model}
        </div>
      ) : null}
    </div>
  );
}
