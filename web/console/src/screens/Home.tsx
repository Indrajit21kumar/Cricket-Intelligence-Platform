// Home / dashboard — identity, the active academy (tenant scope for uploads),
// and entry points to the hero flows. Calm, one primary action (D7).
import { Link } from "react-router-dom";
import { api, CipError } from "../lib/api";
import { useSession } from "../lib/session";
import { Button, Card, EmptyState, Pill, SectionTitle, Select } from "../ui";
import { useState } from "react";

// Demo academies seeded in the DB (fixed UUIDs). In the real product these
// come from the Academy service (M18) + an invitation flow.
const DEMO_ACADEMIES = [
  { id: "11111111-1111-1111-1111-111111111111", name: "PIR Cricket Academy" },
  { id: "22222222-2222-2222-2222-222222222222", name: "Delhi Cricket Club" },
  { id: "33333333-3333-3333-3333-333333333333", name: "Mumbai Youth Cricket" },
];

export function Home() {
  const { me, tenantId, setTenant, refreshMe } = useSession();
  const [joinId, setJoinId] = useState(DEMO_ACADEMIES[0].id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!me) return null;
  const active = me.memberships.filter((m) => m.status === "active");
  const tenantName = (id: string) => DEMO_ACADEMIES.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  const join = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.joinTenant(joinId, "player");
      await refreshMe();
      setTenant(joinId);
    } catch (e) {
      setError(e instanceof CipError ? e.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Hello{me.display_name ? `, ${me.display_name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{me.email}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {me.roles.map((r) => (
            <Pill key={r} tone="brand">
              {r}
            </Pill>
          ))}
          {me.dob_band === "minor" ? <Pill tone="attention">minor — guardian consent</Pill> : null}
        </div>
      </div>

      <Card>
        <SectionTitle>Active academy</SectionTitle>
        {active.length === 0 ? (
          <EmptyState
            title="You're not in an academy yet"
            body="Join one to upload clips for analysis. (Demo academies are seeded for now.)"
            action={
              <div className="mx-auto flex max-w-sm items-end gap-2">
                <Select value={joinId} onChange={(e) => setJoinId(e.target.value)}>
                  {DEMO_ACADEMIES.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
                <Button onClick={join} disabled={busy}>
                  {busy ? "Joining…" : "Join"}
                </Button>
              </div>
            }
          />
        ) : (
          <div className="flex items-center gap-3">
            <Select value={tenantId ?? ""} onChange={(e) => setTenant(e.target.value)} className="max-w-xs">
              {active.map((m) => (
                <option key={m.tenant_id} value={m.tenant_id}>
                  {tenantName(m.tenant_id)} · {m.role}
                </option>
              ))}
            </Select>
            <span className="text-xs text-slate-400">Uploads are scoped to this academy.</span>
          </div>
        )}
        {error ? <p className="mt-3 text-sm text-critical-fg">{error}</p> : null}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <NavCard
          to="/capture"
          title="Analyse a clip"
          body="Film a batting shot with guidance, upload it, and get an honest quality check before analysis."
          cta="Start capture"
          disabled={active.length === 0}
        />
        <NavCard
          to="/progress"
          title="Progress & Cricket DNA"
          body="Your evolving technical fingerprint and trends against your own baseline."
          cta="View progress"
        />
      </div>
    </div>
  );
}

function NavCard({
  to,
  title,
  body,
  cta,
  disabled,
}: {
  to: string;
  title: string;
  body: string;
  cta: string;
  disabled?: boolean;
}) {
  return (
    <Card className="flex flex-col">
      <h3 className="text-base font-bold text-slate-900">{title}</h3>
      <p className="mt-1 flex-1 text-sm text-slate-500">{body}</p>
      <div className="mt-4">
        {disabled ? (
          <Button variant="secondary" disabled>
            {cta} — join an academy first
          </Button>
        ) : (
          <Link to={to}>
            <Button>{cta}</Button>
          </Link>
        )}
      </div>
    </Card>
  );
}
