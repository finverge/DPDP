import { useEffect, useState } from "react"
import { RadioTower, Search, Trash2, CheckCircle2, Rss } from "lucide-react"
import { api, ApiError, type RegulatoryWatchSource, type RegulatoryWatchAlert } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Badge, Input, Textarea, Select, Loading, EmptyState } from "@/components/ui"

const STATUS_TONE: Record<string, "muted" | "success" | "warning" | "danger" | "info"> = {
  ok: "success", error: "danger", new: "warning", acknowledged: "muted",
}

const CATEGORY_LABEL: Record<string, string> = { dpdp: "DPDP", ckycr: "CKYCR / TrustGrid" }
const CATEGORY_TONE: Record<string, "muted" | "success" | "warning" | "danger" | "info"> = { dpdp: "info", ckycr: "warning" }
function categoryLabel(category: string) { return CATEGORY_LABEL[category] ?? category }
function categoryTone(category: string) { return CATEGORY_TONE[category] ?? "muted" }

export function RegulatoryWatch() {
  const session = useSession()
  const isPlatformAdmin = session?.role === "platform_admin"

  const [sources, setSources] = useState<RegulatoryWatchSource[]>([])
  const [alerts, setAlerts] = useState<RegulatoryWatchAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [newName, setNewName] = useState("")
  const [newUrl, setNewUrl] = useState("")
  const [newKind, setNewKind] = useState<"page_hash" | "rss">("page_hash")
  const [newCategory, setNewCategory] = useState("dpdp")
  const [categoryFilter, setCategoryFilter] = useState("all")
  const [ackTarget, setAckTarget] = useState<RegulatoryWatchAlert | null>(null)
  const [ackNote, setAckNote] = useState("")

  function load() {
    setLoading(true)
    Promise.all([api.listRegWatchSources(), api.listRegWatchAlerts()])
      .then(([s, a]) => { setSources(s); setAlerts(a) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  async function handleAddSource() {
    setError(null); setBusy(true)
    try {
      await api.addRegWatchSource({ name: newName, url: newUrl, created_by: session?.email ?? "platform_admin", source_kind: newKind, category: newCategory })
      setNewName(""); setNewUrl(""); setNewKind("page_hash"); setNewCategory("dpdp"); load()
    } catch (err) { setError(err instanceof ApiError ? err.message : "Could not add the source.") }
    finally { setBusy(false) }
  }

  async function handleCheckNow(source: RegulatoryWatchSource) {
    setBusy(true)
    try { await api.checkRegWatchSourceNow(source.id); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not check this source.") }
    finally { setBusy(false) }
  }

  async function handleCheckAll() {
    setBusy(true)
    try { await api.checkAllRegWatchSources(); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not run the check.") }
    finally { setBusy(false) }
  }

  async function handleDelete(source: RegulatoryWatchSource) {
    setBusy(true)
    try { await api.deleteRegWatchSource(source.id); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not remove this source.") }
    finally { setBusy(false) }
  }

  async function handleAcknowledge() {
    if (!ackTarget) return
    setBusy(true)
    try {
      await api.acknowledgeRegWatchAlert(ackTarget.id, { acknowledged_by: session?.email ?? "platform_admin", note: ackNote })
      setAckTarget(null); setAckNote(""); load()
    } catch (err) { setError(err instanceof ApiError ? err.message : "Could not acknowledge this alert.") }
    finally { setBusy(false) }
  }

  if (loading) return <Loading />

  return (
    <div>
      <PageHeader
        title="Regulatory-Change Watch"
        subtitle="BRD Sec. 6.6 — best-effort page-change detection on official sources; a human maps what changed to affected config (no official feed exists to automate this end-to-end)."
        action={isPlatformAdmin ? <Button variant="secondary" onClick={handleCheckAll} disabled={busy}><Search className="h-3.5 w-3.5" /> Check all now</Button> : undefined}
      />

      {error && <p className="text-sm text-[#D6394A] mb-4">{error}</p>}

      {isPlatformAdmin && (
        <Card className="mb-6">
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Add a source</h2>
          <div className="grid grid-cols-4 gap-3 mb-3">
            <div>
              <label htmlFor="regwatch-name" className="block text-xs font-medium text-[#5B6B7A] mb-1">Name</label>
              <Input id="regwatch-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="MeitY DPDP framework page" />
            </div>
            <div>
              <label htmlFor="regwatch-url" className="block text-xs font-medium text-[#5B6B7A] mb-1">URL</label>
              <Input
                id="regwatch-url" value={newUrl} onChange={(e) => setNewUrl(e.target.value)}
                placeholder={newKind === "rss" ? "https://www.rbi.org.in/notifications_rss.xml" : "https://www.meity.gov.in/data-protection-framework"}
              />
            </div>
            <div>
              <label htmlFor="regwatch-kind" className="block text-xs font-medium text-[#5B6B7A] mb-1">Detection mode</label>
              <Select id="regwatch-kind" value={newKind} onChange={(e) => setNewKind(e.target.value as "page_hash" | "rss")}>
                <option value="page_hash">Page (whole-page hash diff)</option>
                <option value="rss">RSS feed (per-item diff)</option>
              </Select>
            </div>
            <div>
              <label htmlFor="regwatch-category" className="block text-xs font-medium text-[#5B6B7A] mb-1">Compliance domain</label>
              <Select id="regwatch-category" value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
                <option value="dpdp">DPDP</option>
                <option value="ckycr">CKYCR / TrustGrid</option>
              </Select>
            </div>
          </div>
          <Button onClick={handleAddSource} disabled={busy || !newName || !newUrl}>Add source</Button>
        </Card>
      )}

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-[#0B2A42]">Watched sources</h2>
        <div className="flex gap-1.5">
          {["all", ...Array.from(new Set(sources.map((s) => s.category)))].map((c) => (
            <button
              key={c} onClick={() => setCategoryFilter(c)}
              className={`text-xs px-2.5 py-1 rounded-full border ${categoryFilter === c ? "bg-[#1E88E5] text-white border-[#1E88E5]" : "bg-white text-[#5B6B7A] border-[#D8DEE4]"}`}
            >
              {c === "all" ? "All" : categoryLabel(c)}
            </button>
          ))}
        </div>
      </div>
      {sources.length === 0 ? (
        <EmptyState title="No sources configured" description="Nothing is being watched yet." />
      ) : (
        <div className="space-y-2 mb-6">
          {sources.filter((s) => categoryFilter === "all" || s.category === categoryFilter).map((s) => (
            <Card key={s.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {s.source_kind === "rss" ? (
                      <Rss className="h-3.5 w-3.5 text-[#1E88E5] shrink-0" />
                    ) : (
                      <RadioTower className="h-3.5 w-3.5 text-[#1E88E5] shrink-0" />
                    )}
                    <span className="text-sm font-medium text-[#0B2A42]">{s.name}</span>
                    <Badge tone="info">{s.source_kind === "rss" ? "RSS" : "page"}</Badge>
                    <Badge tone={categoryTone(s.category)}>{categoryLabel(s.category)}</Badge>
                    {s.last_status && <Badge tone={STATUS_TONE[s.last_status] ?? "muted"}>{s.last_status}</Badge>}
                    {!s.active && <Badge tone="muted">paused</Badge>}
                  </div>
                  <div className="text-xs text-[#5B6B7A] mt-1 truncate">{s.url}</div>
                  <div className="text-xs text-[#5B6B7A] mt-1">
                    {s.last_checked_at ? `last checked ${new Date(s.last_checked_at).toLocaleString()}` : "never checked"}
                  </div>
                  {s.last_error && <div className="text-xs text-[#D6394A] mt-1">{s.last_error}</div>}
                </div>
                {isPlatformAdmin && (
                  <div className="flex gap-1.5 shrink-0">
                    <Button variant="secondary" onClick={() => handleCheckNow(s)} disabled={busy}>Check now</Button>
                    <button title="Remove" onClick={() => handleDelete(s)} disabled={busy} className="p-1.5 rounded-lg text-[#D6394A] hover:bg-[#D6394A]/10"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Alerts</h2>
      {alerts.length === 0 ? (
        <EmptyState title="No changes detected" description="Every watched source's content matched its last known hash." />
      ) : (
        <div className="space-y-2">
          {alerts.map((a) => (
            <Card key={a.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#0B2A42]">{a.source_name}</span>
                    <Badge tone={STATUS_TONE[a.status] ?? "muted"}>{a.status}</Badge>
                  </div>
                  {a.detail && <div className="text-sm text-[#0B2A42] mt-1">{a.detail}</div>}
                  <div className="text-xs text-[#5B6B7A] mt-1 truncate">{a.url}</div>
                  <div className="text-xs text-[#5B6B7A] mt-1">detected {new Date(a.detected_at).toLocaleString()}</div>
                  {a.note && (
                    <div className="text-xs text-[#0B2A42] mt-2 bg-[#ECEFF1] rounded-lg px-2.5 py-1.5">
                      {a.note} — <span className="text-[#5B6B7A]">by {a.acknowledged_by}</span>
                    </div>
                  )}
                </div>
                {isPlatformAdmin && a.status === "new" && (
                  <Button variant="secondary" onClick={() => { setAckTarget(a); setAckNote("") }} disabled={busy}>
                    <CheckCircle2 className="h-3.5 w-3.5" /> Acknowledge
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {ackTarget && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 px-4" onClick={() => setAckTarget(null)}>
          <div className="bg-white rounded-xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold text-[#0B2A42] mb-1">Acknowledge change</h2>
            <p className="text-xs text-[#5B6B7A] mb-3">{ackTarget.source_name} — what actually changed, and which tenant config fields it affects (or note it was a false positive).</p>
            <Textarea
              rows={4} value={ackNote} onChange={(e) => setAckNote(e.target.value)} className="mb-3"
              aria-label="What changed and its config impact"
              placeholder="e.g. Revised breach-intimation format adds a 'root cause' field — maps to Grievance.description guidance for all tenants."
            />
            <div className="flex gap-2">
              <Button onClick={handleAcknowledge} disabled={busy || !ackNote}>Save</Button>
              <Button variant="secondary" onClick={() => setAckTarget(null)}>Cancel</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
