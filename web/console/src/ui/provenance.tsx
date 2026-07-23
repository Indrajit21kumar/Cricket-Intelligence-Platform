// Provenance + confidence primitives — the visual enforcement of the Trust
// Doctrine (Book 6 §7, UX-02, AC-UX-02). A measured value is NEVER styled like
// an estimated/modelled one, and meaning is carried by an icon + text label,
// not colour alone (WCAG AA, §11).

export type Provenance = "measured" | "estimated" | "modelled";

const PROVENANCE_META: Record<
  Provenance,
  { label: string; short: string; glyph: string; cls: string; title: string }
> = {
  measured: {
    label: "Measured",
    short: "meas.",
    glyph: "◉", // fisheye — a solid, directly-observed mark
    cls: "bg-measured-bg text-measured-fg ring-measured-ring",
    title: "Directly computed from the observed pose/bat — a real measurement.",
  },
  estimated: {
    label: "Estimated",
    short: "est.",
    glyph: "≈", // almost-equal — an approximation
    cls: "bg-estimated-bg text-estimated-fg ring-estimated-ring",
    title: "Inferred, not directly measured. Read with its confidence.",
  },
  modelled: {
    label: "Modelled",
    short: "model",
    glyph: "◷", // forward-looking arc — a prediction
    cls: "bg-modelled-bg text-modelled-fg ring-modelled-ring",
    title: "A forward-looking model output, not an observation.",
  },
};

export function ProvenanceBadge({
  provenance,
  compact = false,
}: {
  provenance: Provenance;
  compact?: boolean;
}) {
  const m = PROVENANCE_META[provenance];
  return (
    <span
      title={m.title}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${m.cls}`}
    >
      <span aria-hidden="true">{m.glyph}</span>
      <span>{compact ? m.short : m.label}</span>
    </span>
  );
}

// A small labelled confidence bar. Confidence MUST be shown wherever a value is
// estimated/modelled; low confidence is de-emphasised, never hidden (§7).
export function ConfidenceIndicator({
  confidence,
}: {
  confidence: number | null | undefined;
}) {
  if (confidence == null) return null;
  const pct = Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  const low = pct < 50;
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${low ? "opacity-70" : ""}`}
      title={`Confidence ${pct}%`}
    >
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
        <span
          className={`block h-full rounded-full ${low ? "bg-attention-ring" : "bg-brand-500"}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="tnum text-[11px] font-medium text-slate-500">{pct}%</span>
    </span>
  );
}
