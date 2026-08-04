// Capture guidance -> upload -> quality result (Book 6 §5, §6-lite; on M05).
// The guidance checklist shares its thresholds with the server quality gate, so
// on-device guidance and the post-upload result agree (UX-04). A rejected clip
// gets a specific, non-punitive re-film prompt from the gate's own reasons
// (AC-UX-04).
import { useEffect, useRef, useState } from "react";
import {
  api,
  CipError,
  type BiomechanicsReport,
  type CaptureGuidance,
  type CompleteResponse,
  type MetricEntry,
  type PoseRun,
  type QualityFlag,
} from "../lib/api";
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

// The pose run is produced asynchronously by the pose worker consuming
// `video.normalized`, so the clip is admitted before the run exists. Real
// pose inference is per-frame on CPU — a few seconds of footage takes tens of
// seconds — so the budget is generous; after it, say so honestly rather than
// hang or imply failure.
const POSE_POLL_ATTEMPTS = 90;
const POSE_POLL_INTERVAL_MS = 1000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function pollPose(correlationId: string): Promise<PoseRun | null> {
  for (let i = 0; i < POSE_POLL_ATTEMPTS; i++) {
    try {
      return await api.getPose(correlationId);
    } catch (e) {
      if (!(e instanceof CipError) || e.status !== 404) throw e;
      await sleep(POSE_POLL_INTERVAL_MS);
    }
  }
  return null;
}

// The biomechanics report follows the pose run (its worker consumes
// pose.keypoints), so it arrives shortly after — a much shorter wait than
// pose itself, which is the per-frame inference.
const REPORT_POLL_ATTEMPTS = 30;

async function pollReport(correlationId: string): Promise<BiomechanicsReport | null> {
  for (let i = 0; i < REPORT_POLL_ATTEMPTS; i++) {
    try {
      return await api.getBiomechanics(correlationId);
    } catch (e) {
      if (!(e instanceof CipError) || e.status !== 404) throw e;
      await sleep(POSE_POLL_INTERVAL_MS);
    }
  }
  return null;
}

// Plain-English reasons a metric is absent, keyed by M10's disabled_reason.
// Mirrors report-service's WITHHELD_EXPLANATIONS so the console can explain a
// gap even when it reads M10 directly rather than through a M14 report.
const WITHHELD_REASONS: Record<string, string> = {
  depth_unresolved:
    "Rotation about the body's vertical axis needs two camera angles — a single camera cannot see it.",
  scale_unresolved:
    "No real-world scale was established, so distances and speeds can't be given in cm or m/s.",
  crease_axis_unresolved:
    "The camera angle couldn't be resolved. Film side-on for across-the-crease measurements.",
  no_input_data: "This needs bat tracking, which isn't available yet.",
};

export function Capture() {
  const { me, tenantId } = useSession();
  const [guidance, setGuidance] = useState<CaptureGuidance | null>(null);
  const [gErr, setGErr] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("guidance");
  const [sourceType, setSourceType] = useState("mobile");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [result, setResult] = useState<CompleteResponse | null>(null);
  const [pose, setPose] = useState<PoseRun | null>(null);
  const [posePending, setPosePending] = useState(false);
  const [bio, setBio] = useState<BiomechanicsReport | null>(null);
  const [bioPending, setBioPending] = useState(false);
  const [rejectFlags, setRejectFlags] = useState<QualityFlag[]>([]);
  const [rejectReasons, setRejectReasons] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.captureGuidance().then(setGuidance).catch((e) => setGErr(e instanceof CipError ? e.message : "Failed to load guidance"));
  }, []);

  const reset = () => {
    setStage("guidance");
    setFile(null);
    setPose(null);
    setPosePending(false);
    setBio(null);
    setBioPending(false);
    setProgress(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const analyse = async () => {
    if (!me || !file) return;
    setStage("working");
    setError(null);
    setPose(null);
    setPosePending(false);
    setRejectFlags([]);
    setRejectReasons([]);
    try {
      const correlationId = crypto.randomUUID();
      // The real file's own type + size — the server validates both.
      setProgress("Creating the ingestion…");
      const created = await api.createVideo(
        {
          person_id: me.person_id,
          source_type: sourceType,
          content_type: file.type || "video/mp4",
          size_bytes: file.size,
        },
        correlationId
      );

      setProgress(`Uploading ${formatBytes(file.size)}…`);
      await api.uploadRaw(created.ingestion_id, file);

      setProgress("Preprocessing, calibrating, and running the quality gate…");
      const done = await api.completeVideo(created.ingestion_id);
      setResult(done);
      setStage("admitted");

      // Admitted -> M06 runs off the published event. Surface the real run.
      setPosePending(true);
      setProgress(null);
      const run = await pollPose(correlationId);
      setPose(run);
      setPosePending(false);

      // Biomechanics only exists if pose found a subject to measure.
      if (run && run.quality !== "rejected") {
        setBioPending(true);
        setBio(await pollReport(correlationId));
        setBioPending(false);
      }
    } catch (e) {
      setProgress(null);
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
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-sm font-medium text-slate-700">Video file</span>
              <input
                ref={fileInput}
                type="file"
                accept="video/*"
                disabled={stage === "working"}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded-lg border border-slate-300 text-sm text-slate-600 file:mr-3 file:cursor-pointer file:rounded-l-lg file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-brand-700 hover:file:bg-brand-100 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-60"
              />
              <span className="mt-1 block text-xs text-slate-500">
                {file
                  ? `${file.name} · ${formatBytes(file.size)} · ${file.type || "unknown type"}`
                  : "Pick the clip to analyse — one complete stroke, MP4/MOV/WebM."}
              </span>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Source</span>
              <Select
                value={sourceType}
                disabled={stage === "working"}
                onChange={(e) => setSourceType(e.target.value)}
              >
                {["mobile", "dslr", "nets", "match"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </label>
          </div>
          {error ? <p className="mt-3 rounded-lg bg-attention-bg px-3 py-2 text-sm text-attention-fg">{error}</p> : null}
          <div className="mt-4">
            <Button onClick={analyse} disabled={stage === "working" || !file}>
              {stage === "working" ? "Analysing…" : "Upload & analyse"}
            </Button>
          </div>
          {stage === "working" && progress ? <Loading label={progress} /> : null}
        </Card>
      ) : null}

      {stage === "admitted" && result ? (
        <AdmittedResult
          result={result}
          pose={pose}
          posePending={posePending}
          bio={bio}
          bioPending={bioPending}
          onAgain={reset}
        />
      ) : null}
      {stage === "rejected" ? (
        <RejectPrompt flags={rejectFlags} reasons={rejectReasons} onAgain={reset} />
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

function AdmittedResult({
  result,
  pose,
  posePending,
  bio,
  bioPending,
  onAgain,
}: {
  result: CompleteResponse;
  pose: PoseRun | null;
  posePending: boolean;
  bio: BiomechanicsReport | null;
  bioPending: boolean;
  onAgain: () => void;
}) {
  const conf = result.spatial_confidence;
  const confTone = conf === "high" ? "success" : conf === "medium" ? "brand" : "attention";
  return (
    <>
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Clip admitted</SectionTitle>
        <Pill tone="success">ready for analysis</Pill>
      </div>
      <p className="text-sm text-slate-600">
        Your clip passed the quality gate, was normalised, and published for the analysis pipeline.
        The measurements below were read from the file you uploaded.
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

    <PoseResult pose={pose} pending={posePending} />
    {pose && pose.quality !== "rejected" ? (
      <BiomechanicsResult report={bio} pending={bioPending} />
    ) : null}
    </>
  );
}

// The stroke's measurements (M10). Shows only metrics that carry a real
// number, and explains every one it cannot give — a coach who can't find
// X-Factor should learn it needs a second camera, not be left guessing.
function BiomechanicsResult({
  report,
  pending,
}: {
  report: BiomechanicsReport | null;
  pending: boolean;
}) {
  if (pending) {
    return (
      <Card>
        <SectionTitle>Stroke measurements</SectionTitle>
        <Loading label="Measuring the body through the stroke…" />
      </Card>
    );
  }
  if (!report) {
    return (
      <Card>
        <SectionTitle>Stroke measurements</SectionTitle>
        <EmptyState
          title="No measurements yet"
          body="Pose succeeded but the biomechanics engine hasn't reported back. Check that biomechanics-service and its worker are running."
        />
      </Card>
    );
  }

  const entries = Object.entries(report.metrics);
  const delivered = entries.filter(([, m]) => m.value !== null);
  const withheld = entries.filter(([, m]) => m.value === null);

  // Group the withheld metrics by reason so the reader gets four
  // explanations, not twelve repetitions of the same sentence.
  const grouped = new Map<string, string[]>();
  for (const [id, m] of withheld) {
    const reason = m.disabled_reason || "no_input_data";
    grouped.set(reason, [...(grouped.get(reason) ?? []), id]);
  }

  const t = report.phase_boundaries;
  const fps = report.quality?.fps || 30;
  const phaseOrder = ["stance", "backlift", "downswing", "impact", "follow_through"];

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Stroke measurements</SectionTitle>
        <Pill tone={report.provisional ? "attention" : "success"}>
          {report.provisional ? "provisional" : `${delivered.length} measured`}
        </Pill>
      </div>

      {Object.keys(t).length > 0 ? (
        <>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Stroke timing
          </div>
          <div className="mb-4 grid grid-cols-2 gap-x-4 sm:grid-cols-5">
            {phaseOrder
              .filter((p) => p in t)
              .map((p) => (
                <div key={p} className="border-b border-slate-100 py-2">
                  <div className="text-xs capitalize text-slate-500">{p.replace(/_/g, " ")}</div>
                  <div className="text-sm font-semibold text-slate-800">
                    {(t[p] / fps).toFixed(2)}s
                  </div>
                </div>
              ))}
          </div>
          <p className="mb-4 text-xs text-slate-400">
            Timing derived from hand motion ({report.phase_method.replace(/_/g, " ")}) — no ball
            tracking was involved.
          </p>
        </>
      ) : null}

      {delivered.length > 0 ? (
        <>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Measurements
          </div>
          <div className="space-y-1">
            {delivered.map(([id, m]) => (
              <MetricRow
                key={id}
                label={(m.name || id).replace(/_/g, " ")}
                value={formatMetric(m)}
                unit={m.unit === "ratio" ? undefined : m.unit || undefined}
                provenance={m.provenance === "estimated" ? "estimated" : "measured"}
              />
            ))}
          </div>
        </>
      ) : null}

      {grouped.size > 0 ? (
        <div className="mt-5">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Not measured ({withheld.length})
          </div>
          <ul className="space-y-2">
            {[...grouped.entries()].map(([reason, ids]) => (
              <li key={reason} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
                <span className="font-medium text-slate-700">{ids.join(", ")}</span>
                <span className="block text-slate-500">
                  {WITHHELD_REASONS[reason] ?? reason.replace(/_/g, " ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

function formatMetric(m: MetricEntry): string {
  if (m.value === null) return "—";
  return Math.abs(m.value) >= 100 ? m.value.toFixed(0) : m.value.toFixed(2);
}

// The pose run (M06) for this clip. Body keypoints are real when the service
// runs with CIP_USE_REAL_POSE_MODEL=true; bat, ball and shot detection are
// still fakes, so nothing downstream of pose is shown here.
function PoseResult({ pose, pending }: { pose: PoseRun | null; pending: boolean }) {
  if (pending) {
    return (
      <Card>
        <SectionTitle>Pose analysis</SectionTitle>
        <Loading label="Running the pose engine over your frames — this takes a while on CPU…" />
      </Card>
    );
  }
  if (!pose) {
    return (
      <Card>
        <SectionTitle>Pose analysis</SectionTitle>
        <EmptyState
          title="Still waiting on the pose engine"
          body="The clip was published for analysis, but no run has come back yet. It may still be processing — reload in a moment. If it never arrives, check that pose-service and its worker are running."
        />
      </Card>
    );
  }

  const rejected = pose.quality === "rejected";
  const tone = rejected ? "attention" : pose.quality === "provisional" ? "brand" : "success";
  const isRealModel = !pose.model_version.startsWith("fake-");
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Pose analysis</SectionTitle>
        <Pill tone={tone}>{pose.quality}</Pill>
      </div>

      {rejected ? (
        <p className="text-sm text-slate-600">
          The pose engine could not settle on a single subject
          {pose.rejection_code ? ` (${pose.rejection_code.toLowerCase().replace(/_/g, " ")})` : ""}.
          It refuses to guess rather than analyse the wrong player.
        </p>
      ) : (
        <p className="text-sm text-slate-600">
          Body keypoints were tracked across the clip in the CIP coordinate frame.
        </p>
      )}

      <div className="mt-4 space-y-1">
        <MetricRow label="Subject" value={pose.subject_status.replace(/_/g, " ")} />
        <MetricRow label="Frames analysed" value={String(pose.frame_count)} />
        <MetricRow
          label="Mean joint confidence"
          value={pose.mean_confidence !== null ? pose.mean_confidence.toFixed(3) : "—"}
          provenance="measured"
        />
        <MetricRow label="Model" value={pose.model_version} />
        <div className="flex items-center justify-between gap-3 py-2">
          <span className="text-sm text-slate-600">Depth (Z)</span>
          <ProvenanceBadge provenance={pose.depth_estimated ? "estimated" : "measured"} compact />
        </div>
      </div>

      {!isRealModel ? (
        <p className="mt-4 rounded-lg bg-attention-bg px-3 py-2 text-sm text-attention-fg">
          These keypoints came from the synthetic model — they are not an analysis of your footage.
          Start pose-service with <code>CIP_USE_REAL_POSE_MODEL=true</code> for real pose estimation.
        </p>
      ) : null}

      <p className="mt-4 text-xs text-slate-400">
        These keypoints feed the stroke measurements below. Bat, ball and shot detection are not
        trained yet, so no shot is named and bat-derived measurements are withheld.
      </p>
    </Card>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
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
