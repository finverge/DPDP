import { useEffect, useState } from "react"
import { Sparkles, X } from "lucide-react"
import { api, ApiError, type Grievance, type GrievanceTriage } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Badge, Textarea, Loading, EmptyState } from "@/components/ui"

const STATUS_TONE: Record<string, "muted" | "success" | "warning" | "danger" | "info"> = {
  Open: "info", "In Progress": "warning", Resolved: "success", Rejected: "muted",
}

export function Grievances() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const [items, setItems] = useState<Grievance[]>([])
  const [statusFilter, setStatusFilter] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Grievance | null>(null)
  const [triage, setTriage] = useState<GrievanceTriage | null>(null)
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    api.listGrievances(tenantId, statusFilter || undefined).then(setItems).finally(() => setLoading(false))
  }
  useEffect(load, [tenantId, statusFilter])

  function openDetail(g: Grievance) {
    setSelected(g); setTriage(null); setNote(""); setError(null)
  }

  async function handleTriage() {
    if (!selected) return
    setBusy(true)
    try {
      const t = await api.triageGrievance(selected.id)
      setTriage(t)
      setNote(t.draft_response)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not triage this grievance.")
    } finally { setBusy(false) }
  }

  async function handleResolve() {
    if (!selected) return
    setBusy(true)
    try {
      await api.resolveGrievance(selected.id, session?.email ?? "compliance_officer", note)
      setSelected(null)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resolve.")
    } finally { setBusy(false) }
  }

  async function handleFlagFrivolous() {
    if (!selected) return
    setBusy(true)
    try {
      await api.flagFrivolous(selected.id, session?.email ?? "compliance_officer", triage?.frivolous_signal_reason ?? undefined)
      setSelected(null)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not flag as frivolous.")
    } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader title="Grievances" subtitle="§13 — a readily available grievance-redressal channel, with an SLA-tracked resolution." />

      <div className="flex gap-2 mb-5">
        {["", "Open", "In Progress", "Resolved", "Rejected"].map((s) => (
          <button
            key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${statusFilter === s ? "bg-[#1d79c3] text-white" : "bg-[#ECEFF1] text-[#5B6B7A] hover:bg-[#dfe4e7]"}`}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      {loading ? <Loading /> : items.length === 0 ? (
        <EmptyState title="No grievances" description="Nothing here yet — a good sign, not a broken page." />
      ) : (
        <div className="space-y-2">
          {items.map((g) => (
            <button key={g.id} onClick={() => openDetail(g)} className="w-full text-left">
              <Card className="hover:border-[#1E88E5]/40 transition-colors">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-[#0B2A42]">{g.subject}</div>
                    <div className="text-xs text-[#5B6B7A] mt-0.5">{g.category} · {new Date(g.created_at).toLocaleDateString()}</div>
                  </div>
                  <Badge tone={STATUS_TONE[g.status] ?? "muted"}>{g.status}</Badge>
                </div>
              </Card>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 px-4" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-xl max-w-lg w-full p-6 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-1">
              <h2 className="text-lg font-semibold text-[#0B2A42]">{selected.subject}</h2>
              <button onClick={() => setSelected(null)} aria-label="Close" className="text-[#5B6B7A] hover:text-[#0B2A42]"><X className="h-5 w-5" /></button>
            </div>
            <div className="flex items-center gap-2 mb-4">
              <Badge tone={STATUS_TONE[selected.status] ?? "muted"}>{selected.status}</Badge>
              <span className="text-xs text-[#5B6B7A]">{selected.category}</span>
            </div>
            <p className="text-sm text-[#1B2530] mb-4">{selected.description}</p>

            {selected.status === "Open" && (
              <>
                {!triage ? (
                  <Button variant="secondary" onClick={handleTriage} disabled={busy} className="mb-4">
                    <Sparkles className="h-3.5 w-3.5 text-[#26A69A]" /> Get AI triage suggestion
                  </Button>
                ) : (
                  <Card className="mb-4 bg-[#26A69A]/5 border-[#26A69A]/30">
                    <div className="text-xs font-medium text-[#0B2A42] mb-1">
                      Suggested severity: <Badge tone={triage.suggested_severity === "high" ? "danger" : "warning"}>{triage.suggested_severity}</Badge>
                      {triage.frivolous_signal && <span className="ml-2 text-[#D6394A]">⚠ possible frivolous complaint</span>}
                    </div>
                    {triage.frivolous_signal_reason && <p className="text-xs text-[#5B6B7A] mb-2">{triage.frivolous_signal_reason}</p>}
                  </Card>
                )}
                <label htmlFor="grievance-resolution-note" className="block text-xs font-medium text-[#5B6B7A] mb-1">Resolution note</label>
                <Textarea id="grievance-resolution-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} className="mb-3" />
                {error && <p className="text-sm text-[#D6394A] mb-3">{error}</p>}
                <div className="flex gap-2">
                  <Button onClick={handleResolve} disabled={busy || !note}>Resolve</Button>
                  <Button variant="danger" onClick={handleFlagFrivolous} disabled={busy}>Flag as frivolous</Button>
                </div>
              </>
            )}

            {selected.status !== "Open" && selected.resolution_note && (
              <Card className="bg-[#ECEFF1]">
                <div className="text-xs font-medium text-[#0B2A42] mb-1">Resolution — by {selected.resolved_by}</div>
                <p className="text-sm text-[#5B6B7A]">{selected.resolution_note}</p>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
