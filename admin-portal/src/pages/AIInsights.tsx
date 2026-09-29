import { useEffect, useState } from "react"
import { AlertTriangle, Sparkles, TrendingDown, HeartHandshake, ShieldAlert } from "lucide-react"
import {
  api, ApiError,
  type DriftFlag, type BreachRisk, type DpiaDraft,
  type ConsentPatternSummary, type TrustScore, type BreachSimulationRun,
} from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Badge, Loading, EmptyState } from "@/components/ui"

export function AIInsights() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const [risk, setRisk] = useState<BreachRisk | null>(null)
  const [flags, setFlags] = useState<DriftFlag[]>([])
  const [dpiaHistory, setDpiaHistory] = useState<DpiaDraft[]>([])
  const [patterns, setPatterns] = useState<ConsentPatternSummary | null>(null)
  const [trust, setTrust] = useState<TrustScore | null>(null)
  const [simRun, setSimRun] = useState<BreachSimulationRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [simBusy, setSimBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    Promise.all([
      api.getBreachRisk(tenantId), api.getDriftFlags(tenantId), api.getDpiaHistory(tenantId),
      api.getConsentPatterns(tenantId), api.getTrustScore(tenantId), api.getLatestBreachSimulation(tenantId),
    ])
      .then(([r, f, h, p, t, s]) => { setRisk(r); setFlags(f); setDpiaHistory(h); setPatterns(p); setTrust(t); setSimRun(s) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [tenantId])

  async function handleGenerateDpia() {
    setError(null); setBusy(true)
    try {
      await api.generateDpia(tenantId, session?.email ?? "dpo")
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate a DPIA snapshot.")
    } finally { setBusy(false) }
  }

  async function handleRunSimulation() {
    setError(null); setSimBusy(true)
    try {
      const run = await api.runBreachSimulation(tenantId, session?.email ?? "dpo")
      setSimRun(run)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not run the breach simulation.")
    } finally { setSimBusy(false) }
  }

  if (loading) return <Loading />

  const latestDpia = dpiaHistory[0]
  const bandTone = risk?.band === "high" ? "danger" : risk?.band === "medium" ? "warning" : "success"
  const simTone = simRun?.readiness_band === "strong" ? "success" : simRun?.readiness_band === "needs_attention" ? "warning" : "danger"
  const trustTone = trust?.band === "high" ? "success" : trust?.band === "medium" ? "warning" : trust?.band === "low" ? "danger" : "muted"
  const statusTone = (status: string) => (status === "pass" ? "success" : status === "warning" ? "warning" : "danger")

  return (
    <div>
      <PageHeader title="AI Insights" subtitle="Deterministic detection & assembly (BRD Sec. 6) — not generative-model output. See app/ai.py for the honest scope statement." />

      <div className="grid grid-cols-2 gap-4 mb-6">
        <Card>
          <div className="flex items-center gap-2 text-xs font-medium text-[#5B6B7A] mb-2">
            <AlertTriangle className="h-3.5 w-3.5" /> Breach-risk score
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-semibold text-[#0B2A42]">{risk?.score ?? 0}</span>
            <Badge tone={bandTone}>{risk?.band} band</Badge>
          </div>
          <p className="text-xs text-[#5B6B7A] mt-2">
            {risk?.factors.drift_flags ?? 0} drift flag(s) · {risk?.factors.masking_blocks ?? 0} masking block(s) in the last {risk?.window_days ?? 30} days
          </p>
        </Card>
        <Card>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-xs font-medium text-[#5B6B7A]">
              <Sparkles className="h-3.5 w-3.5 text-[#26A69A]" /> DPIA snapshots
            </div>
            <Button variant="secondary" onClick={handleGenerateDpia} disabled={busy}>Generate new</Button>
          </div>
          {latestDpia ? (
            <>
              <p className="text-xs text-[#5B6B7A]">Latest: {new Date(latestDpia.created_at).toLocaleString()} · {dpiaHistory.length} total</p>
              <p className="text-xs text-[#5B6B7A] mt-1">
                {String((latestDpia.snapshot_json as { active_consent_count?: number }).active_consent_count ?? 0)} active consent record(s) at generation time
              </p>
            </>
          ) : (
            <p className="text-xs text-[#5B6B7A]">No DPIA generated yet.</p>
          )}
        </Card>
      </div>

      {error && <p className="text-sm text-[#D6394A] mb-4">{error}</p>}

      <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Consent-purpose drift flags</h2>
      {flags.length === 0 ? (
        <EmptyState title="No drift detected" description="Every masking/apply call scoped to a Data Principal had a matching active consent grant." />
      ) : (
        <div className="space-y-2 mb-6">
          {flags.map((f) => (
            <Card key={f.id}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-[#0B2A42]">{f.detail}</div>
                  <div className="text-xs text-[#5B6B7A] mt-0.5">Data Principal: {f.data_principal_id} · by {f.actor}</div>
                </div>
                <span className="text-xs text-[#5B6B7A]">{new Date(f.created_at).toLocaleDateString()}</span>
              </div>
            </Card>
          ))}
        </div>
      )}

      <h2 className="text-sm font-semibold text-[#0B2A42] mb-3 flex items-center gap-2">
        <TrendingDown className="h-4 w-4" /> Consent pattern analytics <span className="font-normal text-[#5B6B7A]">— last {patterns?.window_days ?? 90} days</span>
      </h2>
      {!patterns || patterns.purposes.length === 0 ? (
        <EmptyState title="No consent grants in this window yet" />
      ) : (
        <Card className="mb-6 p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[#5B6B7A] border-b border-[#E2E5EA]">
                <th className="px-4 py-2.5 font-medium">Purpose</th>
                <th className="px-4 py-2.5 font-medium">Granted</th>
                <th className="px-4 py-2.5 font-medium">Withdrawn</th>
                <th className="px-4 py-2.5 font-medium">Withdrawal rate</th>
                <th className="px-4 py-2.5 font-medium">Median days to withdraw</th>
                <th className="px-4 py-2.5 font-medium">Signal</th>
              </tr>
            </thead>
            <tbody>
              {patterns.purposes.map((p) => (
                <tr key={p.purpose} className="border-b border-[#E2E5EA] last:border-0">
                  <td className="px-4 py-2.5 text-[#0B2A42]">{p.purpose}</td>
                  <td className="px-4 py-2.5 text-[#5B6B7A]">{p.granted_count}</td>
                  <td className="px-4 py-2.5 text-[#5B6B7A]">{p.withdrawn_count}</td>
                  <td className="px-4 py-2.5 text-[#5B6B7A]">{(p.withdrawal_rate * 100).toFixed(0)}%</td>
                  <td className="px-4 py-2.5 text-[#5B6B7A]">{p.median_days_to_withdrawal ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    {p.flagged ? (
                      <span title={p.flag_reason ?? ""}><Badge tone="warning">High churn</Badge></span>
                    ) : <Badge tone="muted">Stable</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 mb-6">
        <Card>
          <div className="flex items-center gap-2 text-xs font-medium text-[#5B6B7A] mb-2">
            <HeartHandshake className="h-3.5 w-3.5" /> Privacy trust score
          </div>
          {trust?.score === null || trust === null ? (
            <p className="text-sm text-[#5B6B7A]">No grievances in this window yet.</p>
          ) : (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-4xl font-semibold text-[#0B2A42]">{trust.score}</span>
                <Badge tone={trustTone}>{trust.band} trust</Badge>
              </div>
              <p className="text-xs text-[#5B6B7A] mt-2">
                {trust.grievance_count} grievance(s) · avg sentiment {trust.avg_sentiment} · {((trust.resolution_rate ?? 0) * 100).toFixed(0)}% resolved
              </p>
              {trust.sentiment_by_grievance.length > 0 && (
                <p className="text-xs text-[#5B6B7A] mt-1">
                  Most negative: “{trust.sentiment_by_grievance[0].subject}” ({trust.sentiment_by_grievance[0].band})
                </p>
              )}
            </>
          )}
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-xs font-medium text-[#5B6B7A]">
              <ShieldAlert className="h-3.5 w-3.5" /> Breach simulation & readiness
            </div>
            <Button variant="secondary" onClick={handleRunSimulation} disabled={simBusy}>Run simulation</Button>
          </div>
          {simRun ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-4xl font-semibold text-[#0B2A42]">{simRun.readiness_score}</span>
                <Badge tone={simTone}>{simRun.readiness_band.replace("_", " ")}</Badge>
              </div>
              <p className="text-xs text-[#5B6B7A] mt-2">Last run: {new Date(simRun.created_at).toLocaleString()}</p>
            </>
          ) : (
            <p className="text-sm text-[#5B6B7A]">No simulation run yet — click “Run simulation.”</p>
          )}
        </Card>
      </div>

      {simRun && (
        <>
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Simulation scenarios</h2>
          <div className="space-y-2">
            {simRun.scenario_results_json.map((s) => (
              <Card key={s.id}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[#0B2A42]">{s.title}</span>
                      <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                    </div>
                    <p className="text-xs text-[#5B6B7A] mt-1">{s.detail}</p>
                    {s.remediation && <p className="text-xs text-[#1d79c3] mt-1">Fix: {s.remediation}</p>}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
