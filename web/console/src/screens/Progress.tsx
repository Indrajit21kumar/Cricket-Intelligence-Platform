// Progress + Cricket DNA (Book 6 §9; on M04). The player's attributes, their
// evolving trait fingerprint, and trends against their own baseline. DNA is
// written by M16 (not live yet), so those panels show honest empty states —
// the profile attributes are editable today.
import { useCallback, useEffect, useState } from "react";
import { api, CipError, type DnaTrait, type Profile, type TrendPoint } from "../lib/api";
import { useSession } from "../lib/session";
import {
  Button,
  Card,
  ConfidenceIndicator,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  ProvenanceBadge,
  SectionTitle,
  Select,
} from "../ui";

export function Progress() {
  const { me } = useSession();
  if (!me) return null;
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-6">
      <h1 className="text-2xl font-bold text-slate-900">Progress &amp; Cricket DNA</h1>
      <ProfilePanel personId={me.person_id} />
      <DnaPanel personId={me.person_id} />
      <ProgressPanel personId={me.person_id} />
    </div>
  );
}

function ProfilePanel({ personId }: { personId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ height_cm: "", stance: "right-hand-bat", age_band: "senior", dominant_hand: "right" });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await api.getProfile(personId);
      setProfile(p);
      setMissing(false);
    } catch (e) {
      if (e instanceof CipError && e.status === 404) setMissing(true);
      else setError(e instanceof CipError ? e.message : "Failed to load profile");
    } finally {
      setLoading(false);
    }
  }, [personId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (create: boolean) => {
    const body = {
      height_cm: form.height_cm ? Number(form.height_cm) : null,
      stance: form.stance,
      age_band: form.age_band,
      dominant_hand: form.dominant_hand,
    };
    try {
      const p = create ? await api.createProfile(personId, body) : await api.patchProfile(personId, body);
      setProfile(p);
      setMissing(false);
      setEditing(false);
    } catch (e) {
      setError(e instanceof CipError ? e.message : "Failed to save");
    }
  };

  return (
    <Card>
      <SectionTitle hint="Used to calibrate your analysis">Your attributes</SectionTitle>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : missing ? (
        <EmptyState
          title="Set up your profile"
          body="Height and stance help calibrate your clips accurately."
          action={<Button onClick={() => setEditing(true)}>Add attributes</Button>}
        />
      ) : editing || !profile ? null : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Attr label="Height" value={profile.height_cm ? `${profile.height_cm} cm` : "—"} />
          <Attr label="Stance" value={profile.stance ?? "—"} />
          <Attr label="Age band" value={profile.age_band ?? "—"} />
          <Attr label="Dominant hand" value={profile.dominant_hand ?? "—"} />
          <div className="col-span-2 sm:col-span-4">
            <Button variant="ghost" onClick={() => setEditing(true)}>
              Edit
            </Button>
          </div>
        </div>
      )}

      {editing ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label="Height (cm)">
            <Input type="number" value={form.height_cm} onChange={(e) => setForm({ ...form, height_cm: e.target.value })} />
          </Field>
          <Field label="Stance">
            <Select value={form.stance} onChange={(e) => setForm({ ...form, stance: e.target.value })}>
              <option value="right-hand-bat">right-hand-bat</option>
              <option value="left-hand-bat">left-hand-bat</option>
            </Select>
          </Field>
          <Field label="Age band">
            <Select value={form.age_band} onChange={(e) => setForm({ ...form, age_band: e.target.value })}>
              {["u13", "u16", "u19", "senior"].map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Dominant hand">
            <Select value={form.dominant_hand} onChange={(e) => setForm({ ...form, dominant_hand: e.target.value })}>
              <option value="right">right</option>
              <option value="left">left</option>
            </Select>
          </Field>
          <div className="sm:col-span-2">
            <Button onClick={() => save(missing)}>Save</Button>
            {!missing ? (
              <Button variant="ghost" onClick={() => setEditing(false)} className="ml-2">
                Cancel
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function Attr({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-sm font-semibold text-slate-800">{value}</div>
    </div>
  );
}

function DnaPanel({ personId }: { personId: string }) {
  const [traits, setTraits] = useState<DnaTrait[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getDna(personId)
      .then(setTraits)
      .catch((e) => {
        if (e instanceof CipError && e.status === 404) setTraits([]);
        else setError(e instanceof CipError ? e.message : "Failed to load DNA");
      })
      .finally(() => setLoading(false));
  }, [personId]);

  return (
    <Card>
      <SectionTitle hint="An evolving fingerprint, not a fixed label">Cricket DNA</SectionTitle>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} />
      ) : !traits || traits.length === 0 ? (
        <EmptyState
          title="No Cricket DNA yet"
          body="Your trait fingerprint builds as your clips are analysed. Analysis lands with the pose & biomechanics engines (M06+)."
        />
      ) : (
        <div className="space-y-1">
          {traits.map((t) => (
            <div key={t.trait_key} className="flex items-center justify-between gap-3 border-b border-slate-100 py-2 last:border-0">
              <span className="text-sm text-slate-700">{t.trait_key.replace(/^(trait|style|pref|weak)\./, "")}</span>
              <span className="flex items-center gap-2">
                <span className="tnum text-sm font-semibold text-slate-900">{t.value}</span>
                <ProvenanceBadge provenance={t.provenance} compact />
                <ConfidenceIndicator confidence={t.confidence} />
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ProgressPanel({ personId }: { personId: string }) {
  const [traitKey, setTraitKey] = useState("trait.aggression");
  const [period, setPeriod] = useState("monthly");
  const [points, setPoints] = useState<TrendPoint[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPoints(await api.getProgress(personId, traitKey, period));
    } catch (e) {
      setError(e instanceof CipError ? e.message : "Failed to load progress");
    } finally {
      setLoading(false);
    }
  }, [personId, traitKey, period]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card>
      <SectionTitle>Progress vs your baseline</SectionTitle>
      <div className="mb-3 flex flex-wrap gap-2">
        <Select value={traitKey} onChange={(e) => setTraitKey(e.target.value)} className="max-w-[14rem]">
          {["trait.aggression", "trait.timing", "trait.balance", "trait.power", "trait.footwork"].map((t) => (
            <option key={t} value={t}>
              {t.replace("trait.", "")}
            </option>
          ))}
        </Select>
        <Select value={period} onChange={(e) => setPeriod(e.target.value)} className="max-w-[10rem]">
          {["weekly", "monthly", "yearly"].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !points || points.length === 0 ? (
        <EmptyState title="No trend yet" body="Trends appear once you have analysed clips over time." />
      ) : (
        <Sparkline points={points} />
      )}
    </Card>
  );
}

function Sparkline({ points }: { points: TrendPoint[] }) {
  const values = points.map((p) => Number(p.value)).filter((n) => !Number.isNaN(n));
  if (values.length === 0) return <EmptyState title="No numeric trend" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 480;
  const h = 120;
  const step = values.length > 1 ? w / (values.length - 1) : w;
  const path = values.map((v, i) => `${i === 0 ? "M" : "L"} ${i * step} ${h - ((v - min) / span) * h}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-32 w-full" role="img" aria-label="Trend">
      <path d={path} fill="none" stroke="#2563eb" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      {values.map((v, i) => (
        <circle key={i} cx={i * step} cy={h - ((v - min) / span) * h} r={3} fill="#2563eb" />
      ))}
    </svg>
  );
}
