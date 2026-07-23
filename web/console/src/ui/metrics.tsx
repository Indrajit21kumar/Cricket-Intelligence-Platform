// Metric + score components (Book 6 §3.2, §6, §9). Every metric shows value +
// unit + provenance + confidence together; nothing is a bare number.
import type { ReactNode } from "react";
import { ConfidenceIndicator, ProvenanceBadge, type Provenance } from "./provenance";

export function MetricRow({
  label,
  value,
  unit,
  provenance,
  confidence,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  provenance?: Provenance;
  confidence?: number | null;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 py-2 last:border-0">
      <span className="text-sm text-slate-600">{label}</span>
      <span className="flex items-center gap-2">
        <span className="tnum text-sm font-semibold text-slate-900">
          {value}
          {unit ? <span className="ml-0.5 text-xs font-normal text-slate-400">{unit}</span> : null}
        </span>
        {provenance ? <ProvenanceBadge provenance={provenance} compact /> : null}
        <ConfidenceIndicator confidence={confidence} />
      </span>
    </div>
  );
}

// A glanceable score chip (0–100). Tone shifts subtly with the band; the number
// is always the focus (D1 — tap to expand handled by the caller).
export function ScoreChip({
  label,
  score,
}: {
  label: string;
  score: number | null;
}) {
  const band =
    score == null
      ? "bg-slate-100 text-slate-400"
      : score >= 75
        ? "bg-success-bg text-success-fg"
        : score >= 50
          ? "bg-brand-50 text-brand-700"
          : "bg-attention-bg text-attention-fg";
  return (
    <div className={`rounded-xl px-3 py-2 text-center ${band}`}>
      <div className="tnum text-xl font-extrabold leading-none">{score ?? "—"}</div>
      <div className="mt-1 text-[11px] font-medium uppercase tracking-wide opacity-80">{label}</div>
    </div>
  );
}

// Player value against a reference range (Book 6 §3.2 benchmark bar).
export function BenchmarkBar({
  label,
  value,
  min,
  max,
  unit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
}) {
  const span = max - min || 1;
  const pct = Math.max(0, Math.min(100, ((value - min) / span) * 100));
  return (
    <div className="py-1.5">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-slate-600">{label}</span>
        <span className="tnum font-semibold text-slate-900">
          {value}
          {unit ? <span className="text-slate-400"> {unit}</span> : null}
        </span>
      </div>
      <div className="relative h-2 rounded-full bg-slate-100" aria-hidden="true">
        <span
          className="absolute -top-0.5 h-3 w-1 rounded-full bg-brand-600"
          style={{ left: `calc(${pct}% - 2px)` }}
        />
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] tnum text-slate-400">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
