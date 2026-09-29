import { useEffect, useState } from "react"
import { RefreshCw, Trash2, KeyRound, Webhook as WebhookIcon } from "lucide-react"
import { api, ApiError, type WebhookSubscription, type WebhookDelivery } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Badge, Input, Loading, EmptyState } from "@/components/ui"

const STATUS_TONE: Record<string, "muted" | "success" | "warning" | "danger" | "info"> = {
  success: "success", pending: "warning", failed: "danger",
}

export function Webhooks() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const canManage = session?.role === "tenant_admin" || session?.role === "platform_admin"

  const [eventTypes, setEventTypes] = useState<string[]>([])
  const [subs, setSubs] = useState<WebhookSubscription[]>([])
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [revealedSecret, setRevealedSecret] = useState<{ url: string; secret: string } | null>(null)

  const [newUrl, setNewUrl] = useState("")
  const [newEvents, setNewEvents] = useState<string[]>([])

  function load() {
    if (!tenantId) { setLoading(false); return }
    setLoading(true)
    Promise.all([api.listWebhookEventTypes(), api.listWebhookSubscriptions(tenantId), api.listWebhookDeliveries(tenantId)])
      .then(([types, s, d]) => { setEventTypes(types); setSubs(s); setDeliveries(d) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [tenantId])

  function toggleEvent(evt: string) {
    setNewEvents((prev) => (prev.includes(evt) ? prev.filter((e) => e !== evt) : [...prev, evt]))
  }

  async function handleCreate() {
    setError(null); setBusy(true)
    try {
      const created = await api.createWebhookSubscription({
        tenant_id: tenantId, url: newUrl, events: newEvents, created_by: session?.email ?? "tenant_admin",
      })
      setRevealedSecret({ url: created.url, secret: created.secret })
      setNewUrl(""); setNewEvents([])
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the subscription.")
    } finally { setBusy(false) }
  }

  async function handleToggleActive(sub: WebhookSubscription) {
    setBusy(true)
    try { await api.updateWebhookSubscription(sub.id, { active: !sub.active }); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not update the subscription.") }
    finally { setBusy(false) }
  }

  async function handleRotate(sub: WebhookSubscription) {
    setBusy(true)
    try {
      const rotated = await api.rotateWebhookSecret(sub.id)
      setRevealedSecret({ url: rotated.url, secret: rotated.secret })
    } catch (err) { setError(err instanceof ApiError ? err.message : "Could not rotate the secret.") }
    finally { setBusy(false) }
  }

  async function handleDelete(sub: WebhookSubscription) {
    setBusy(true)
    try { await api.deleteWebhookSubscription(sub.id); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not delete the subscription.") }
    finally { setBusy(false) }
  }

  async function handleRetry(delivery: WebhookDelivery) {
    setBusy(true)
    try { await api.retryWebhookDelivery(delivery.id); load() }
    catch (err) { setError(err instanceof ApiError ? err.message : "Could not retry this delivery.") }
    finally { setBusy(false) }
  }

  if (!tenantId) {
    return (
      <div>
        <PageHeader title="Webhooks" subtitle="§5.4 — outbound event delivery to your registered endpoints." />
        <Card><p className="text-sm text-[#5B6B7A]">No tenant-scoped view for platform_admin yet — this account can act across tenants via the API, but this page is per-tenant today.</p></Card>
      </div>
    )
  }
  if (loading) return <Loading />

  return (
    <div>
      <PageHeader title="Webhooks" subtitle="FSD Sec. 5.4 — subscribe an endpoint to consent/data-access/breach events, HMAC-signed, retried with backoff." />

      {revealedSecret && (
        <Card className="mb-5 bg-[#E0A030]/10 border-[#E0A030]/40">
          <p className="text-xs font-medium text-[#0B2A42] mb-1">Signing secret for {revealedSecret.url} — shown once, save it now:</p>
          <code className="block text-xs bg-white rounded-lg px-3 py-2 break-all border border-[#E2E5EA]">{revealedSecret.secret}</code>
          <button onClick={() => setRevealedSecret(null)} className="text-xs text-[#5B6B7A] hover:text-[#0B2A42] mt-2">Dismiss</button>
        </Card>
      )}
      {error && <p className="text-sm text-[#D6394A] mb-4">{error}</p>}

      {canManage && (
        <Card className="mb-6">
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">New subscription</h2>
          <label htmlFor="webhook-url" className="block text-xs font-medium text-[#5B6B7A] mb-1">Endpoint URL</label>
          <Input id="webhook-url" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="https://processor.example.com/consentbridge-hook" className="mb-3" />
          <label className="block text-xs font-medium text-[#5B6B7A] mb-1">Events</label>
          <div className="flex flex-wrap gap-2 mb-3">
            {eventTypes.map((evt) => (
              <button
                key={evt} type="button" onClick={() => toggleEvent(evt)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${newEvents.includes(evt) ? "bg-[#1d79c3] text-white" : "bg-[#ECEFF1] text-[#5B6B7A] hover:bg-[#dfe4e7]"}`}
              >
                {evt}
              </button>
            ))}
          </div>
          <Button onClick={handleCreate} disabled={busy || !newUrl || newEvents.length === 0}>Create subscription</Button>
        </Card>
      )}

      <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Subscriptions</h2>
      {subs.length === 0 ? (
        <EmptyState title="No webhook subscriptions" description="Add one above to start receiving events." />
      ) : (
        <div className="space-y-2 mb-6">
          {subs.map((sub) => (
            <Card key={sub.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <WebhookIcon className="h-3.5 w-3.5 text-[#1E88E5] shrink-0" />
                    <span className="text-sm font-medium text-[#0B2A42] truncate">{sub.url}</span>
                    <Badge tone={sub.active ? "success" : "muted"}>{sub.active ? "active" : "paused"}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {sub.events.map((e) => <Badge key={e} tone="info">{e}</Badge>)}
                  </div>
                  <div className="text-xs text-[#5B6B7A] mt-2">by {sub.created_by} · {new Date(sub.created_at).toLocaleDateString()}</div>
                </div>
                {canManage && (
                  <div className="flex gap-1.5 shrink-0">
                    <button title="Pause/resume" onClick={() => handleToggleActive(sub)} disabled={busy} className="p-1.5 rounded-lg text-[#5B6B7A] hover:bg-[#ECEFF1]"><RefreshCw className="h-3.5 w-3.5" /></button>
                    <button title="Rotate secret" onClick={() => handleRotate(sub)} disabled={busy} className="p-1.5 rounded-lg text-[#5B6B7A] hover:bg-[#ECEFF1]"><KeyRound className="h-3.5 w-3.5" /></button>
                    <button title="Delete" onClick={() => handleDelete(sub)} disabled={busy} className="p-1.5 rounded-lg text-[#D6394A] hover:bg-[#D6394A]/10"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Recent deliveries</h2>
      {deliveries.length === 0 ? (
        <EmptyState title="No deliveries yet" description="They'll show up here as subscribed events fire." />
      ) : (
        <div className="space-y-2">
          {deliveries.map((d) => (
            <Card key={d.id}>
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#0B2A42]">{d.event_type}</span>
                    <Badge tone={STATUS_TONE[d.status] ?? "muted"}>{d.status}</Badge>
                    <span className="text-xs text-[#5B6B7A]">attempt {d.attempt_count}{d.response_status ? ` · HTTP ${d.response_status}` : ""}</span>
                  </div>
                  {d.response_snippet && <div className="text-xs text-[#5B6B7A] mt-1 truncate">{d.response_snippet}</div>}
                  <div className="text-xs text-[#5B6B7A] mt-1">{new Date(d.created_at).toLocaleString()}</div>
                </div>
                {canManage && d.status !== "success" && (
                  <Button variant="secondary" onClick={() => handleRetry(d)} disabled={busy}>Retry now</Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
