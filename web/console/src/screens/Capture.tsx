// Capture guidance -> upload -> quality result (Book 6 §5, §6-lite; on M05).
// The guidance checklist shares its thresholds with the server quality gate, so
// on-device guidance and the post-upload result agree (UX-04). A rejected clip
// gets a specific, non-punitive re-film prompt from the gate's own reasons
// (AC-UX-04).
import { useEffect, useState } from "react";
import { api, CipError, type CaptureGuidance, type CompleteResponse, type QualityFlag } from "../lib/api";
import { useSession } from "../lib/session";
import {
  Button,
  Card,
  ConfidenceIndicator,
  EmptyState,
  ErrorState,
  Loading,
  MetricRow,
  Pill,
  ProvenanceBadge,
  SectionTitle,
  Select,
} from "../ui";

type Stage = "guidance" | "working" | "admitted" | "rejected";

export function Capture() {
  const { me, tenantId } = useSession();
  const [guidance, setGuidance] = useState<CaptureGuidance | null>(null);
  const [gErr, setGErr] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("guidance");
  const [sourceType, setSourceType] = useState("mobile");
  const [contentType, setContentType] = useState("video/mp4");
  const [result, setResult] = useState<CompleteResponse | null>(null);
  const [rejectFlags, setRejectFlags] = useState<QualityFlag[]>([]);
  const [rejectReasons, setRejectReasons] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.captureGuidance().then(setGuidance).catch((e) => setGErr(e instanceof CipError ? e.message : "Failed to load guidance"));
  }, []);

  const analyse = async () => {
    if (!me) return;
    setStage("working");
    setError(null);
    setRejectFlags([]);
    setRejectReasons([]);
    try {
      const correlationId = crypto.randomUUID();
      const created = await api.createVideo(
        { person_id: me.person_id, source_type: sourceType, content_type: contentType, size_bytes: 4_000_000 },
        correlationId
      );
      // With the dev fake storage the object is present on create, so we go
      // straight to /complete (a real client PUTs to created.upload_url first).
      const done = await api.completeVideo(created.ingestion_id);
      setResult(done);
      setStage("admitted");
    } catch (e) {
      if (e instanceof CipError && e.status === 422) {
        const flags = (e.details?.flags as QualityFlag[] | undefined) ?? [];
        const reasons = (e.details?.reasons as string[] | undefined) ?? [];
        setRejectFlags(flags);
        setRejectReasons(reasons);
        setStage("rejected");
      } else if (e instanceof CipError && e.status === 403) {
        setError("Analysis quota reached for this plan. Upgrade to analyse more clips.");
        setStage("guidance");
      } else {
        setError(e instanceof CipError ? e.message : "Unexpected error");
        setStage("guidance");
      }
    }
  };

  if (!tenantId) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-6">
        <EmptyState title="Join an academy first" body="Uploads are scoped to an academy." />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5 px-4 py-6">
      <h1 className="text-2xl font-bold text-slate-900">Analyse a clip</h1>

      <Card>
        <SectionTitle hint="These match the server quality gate">Capture guidance</SectionTitle>
        {gErr ? (
          <ErrorState message={gErr} />
        ) : !guidance ? (
          <Loading label="Loading guidance…" />
        ) : (
          <GuidanceChecklist thresholds={guidance.thresholds} />
        )}
      </Card>

      {stage === "guidance" || stage === "working" ? (
        <Card>
          <SectionTitle>Upload</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Source</span>
              <Select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                {["mobile", "dslr", "nets", "match"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Format</span>
              <Select value={contentType} onChange={(e) => setContentType(e.target.value)}>
                <option value="video/mp4">MP4</option>
                <option value="video/quicktime">MOV</option>
                <option value="video/webm">WebM</option>
                <option value="image/gif">GIF (unsupported — will be rejected)</option>
              </Select>
            </label>
          </div>
          {error ? <p className="mt-3 rounded-lg bg-attention-bg px-3 py-2 text-sm text-attention-fg">{error}</p> : null}
          <div className="mt-4">
            <Button onClick={analyse} disabled={stage === "working"}>
              {stage === "working" ? "Analysing…" : "Upload & analyse"}
            </Button>
          </div>
          {stage === "working" ? <Loading label="Preprocessing, calibrating, and running the quality gate…" /> : null}
        </Card>
      ) : null}

      {stage === "admitted" && result ? <AdmittedResult result={result} onAgain={() => setStage("guidance")} /> : null}
      {stage === "rejected" ? (
        <RejectPrompt flags={rejectFlags} reasons={rejectReasons} onAgain={() => setStage("guidance")} />
      ) : null}
    </div>
  );
}

function GuidanceChecklist({ thresholds }: { thresholds: Record<string, unknown> }) {
  const angles = (thresholds.supported_angles as string[] | undefined)?.join(" / ") ?? "side-on";
  const [w, h] = [thresholds.min_width, thresholds.min_height];
  const [dmin, dmax] = (thresholds.duration_range_s as [number, number] | undefined) ?? [2, 20];
  const items = [
    { t: "Camera angle", d: `Film ${angles} — set the phone level with the batter.` },
    { t: "Framing", d: "Keep the whole body and bat in frame for the full stroke." },
    { t: "Lighting", d: "Even light; avoid strong backlight or a dark net." },
    { t: "Stability", d: "Use a tripod or prop the phone — steady beats handheld." },
    { t: "Reference", d: "Include the stumps in frame to calibrate more confidently." },
    { t: "Format", d: `At least ${w}×${h}, ${dmin}–${dmax}s, 30fps+.` },
  ];
  return (
    <ul className="space-y-2">
      {items.map((it) => (
        <li key={it.t} className="flex gap-3">
          <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700" aria-hidden="true">
            ✓
          </span>
          <span className="text-sm">
            <span className="font-semibold text-slate-800">{it.t}. </span>
            <span className="text-slate-600">{it.d}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function AdmittedResult({ result, onAgain }: { result: CompleteResponse; onAgain: () => void }) {
  const conf = result.spatial_confidence;
  const confTone = conf === "high" ? "success" : conf === "medium" ? "brand" : "attention";
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Clip admitted</SectionTitle>
        <Pill tone="success">ready for analysis</Pill>
      </div>
      <p className="text-sm text-slate-600">
        Your clip passed the quality gate, was normalised, and published for the analysis pipeline.
        The coaching report arrives when the pose &amp; biomechanics engines (M06+) are live.
      </p>

      <div className="mt-4 space-y-1">
        <MetricRow label="Camera angle" value={result.camera_angle.replace("_", "-")} />
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 py-2">
          <span className="text-sm text-slate-600">Spatial confidence</span>
          <span className="flex items-center gap-2">
            <Pill tone={confTone}>{conf}</Pill>
            <ProvenanceBadge provenance={result.depth_estimated ? "estimated" : "measured"} compact />
          </span>
        </div>
        <MetricRow
          label="Pixel-to-metre scale"
          value={result.pixel_to_meter ? result.pixel_to_meter.toExponential(2) : "—"}
          unit="m/px"
          provenance="measured"
        />
        <MetricRow label="Calibration method" value={result.calibration_method} />
        <MetricRow label="Frames / fps" value={`${result.frame_count} · ${result.fps}`} />
        <div className="flex items-center justify-between py-2 text-xs text-slate-400">
          <span>Depth (Z) from a single camera is inferred, so it carries a wider tolerance.</span>
          <ConfidenceIndicator confidence={conf === "high" ? 0.9 : conf === "medium" ? 0.6 : 0.3} />
        </div>
      </div>

      {result.flags.length > 0 ? (
        <div className="mt-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Notes</div>
          <ul className="space-y-2">
            {result.flags.map((f) => (
              <li key={f.code} className="flex items-start gap-2 rounded-lg bg-attention-bg px-3 py-2 text-sm text-attention-fg">
                <span aria-hidden="true">⚠</span>
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5">
        <Button variant="secondary" onClick={onAgain}>
          Analyse another
        </Button>
      </div>
    </Card>
  );
}

function RejectPrompt({
  flags,
  reasons,
  onAgain,
}: {
  flags: QualityFlag[];
  reasons: string[];
  onAgain: () => void;
}) {
  const shown = flags.length > 0 ? flags : reasons.map((code) => ({ code, severity: "fail" as const, message: humaniseReason(code) }));
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between">
        <SectionTitle>Let's re-film this one</SectionTitle>
        <Pill tone="attention">not analysed</Pill>
      </div>
      <p className="text-sm text-slate-600">
        No analysis unit was used. Fix the points below and try again — small changes make a big
        difference to accuracy.
      </p>
      <ul className="mt-4 space-y-2">
        {shown.map((f) => (
          <li key={f.code} className="flex items-start gap-2 rounded-lg bg-critical-bg px-3 py-2 text-sm text-critical-fg">
            <span aria-hidden="true">•</span>
            <span>{f.message}</span>
          </li>
        ))}
      </ul>
      <div className="mt-5">
        <Button onClick={onAgain}>Try again</Button>
      </div>
    </Card>
  );
}

function humaniseReason(code: string): string {
  const map: Record<string, string> = {
    unsupported_content_type: "That file format isn't supported. Use MP4, MOV, or WebM.",
    unsupported_source_type: "Unsupported capture source.",
    file_too_large: "The file is too large. Trim it to a single stroke.",
    file_too_small: "The file looks incomplete. Re-record the stroke.",
  };
  return map[code] ?? code.replace(/_/g, " ");
}
