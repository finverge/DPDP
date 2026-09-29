import { useEffect, useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { api, ApiError, type MaskingPolicy } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Input, Select, Loading, EmptyState } from "@/components/ui"

const STRATEGIES = ["allow", "redact", "mask_last4", "mask_account", "mask_device", "mask_ip", "omit"]

export function MaskingPolicies() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const [policies, setPolicies] = useState<MaskingPolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [purpose, setPurpose] = useState("")
  const [rules, setRules] = useState<{ field: string; strategy: string }[]>([{ field: "", strategy: "allow" }])
  const [busy, setBusy] = useState(false)

  function load() {
    setLoading(true)
    api.listMaskingPolicies(tenantId).then(setPolicies).finally(() => setLoading(false))
  }
  useEffect(load, [tenantId])

  function updateRule(i: number, patch: Partial<{ field: string; strategy: string }>) {
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }

  async function handleSave() {
    setError(null); setBusy(true)
    try {
      const field_rules: Record<string, string> = {}
      for (const r of rules) if (r.field.trim()) field_rules[r.field.trim()] = r.strategy
      if (!purpose.trim() || Object.keys(field_rules).length === 0) {
        setError("A purpose and at least one field rule are required.")
        return
      }
      await api.upsertMaskingPolicy({ tenant_id: tenantId, purpose: purpose.trim(), field_rules, created_by: session?.email ?? "admin" })
      setPurpose(""); setRules([{ field: "", strategy: "allow" }])
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the policy.")
    } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader title="Masking Policies" subtitle="§8(4)-(5) — default-deny per field. A field not listed here is never shared, for that purpose, by anyone." />

      {loading ? <Loading /> : policies.length === 0 ? (
        <EmptyState title="No masking policies configured yet" description="Any /masking/apply call for this tenant will be blocked (fail-closed) until you add one." />
      ) : (
        <div className="space-y-3 mb-6">
          {policies.map((p) => (
            <Card key={p.id}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-[#0B2A42]">{p.purpose}</h3>
                <span className="text-xs text-[#5B6B7A]">by {p.created_by}</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(p.field_rules).map(([field, strategy]) => (
                  <span key={field} className="inline-flex items-center gap-1 rounded-md bg-[#ECEFF1] px-2 py-1 text-xs">
                    <span className="font-medium text-[#0B2A42]">{field}</span>
                    <span className="text-[#5B6B7A]">→ {strategy}</span>
                  </span>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">New / update policy</h2>
        <label htmlFor="masking-purpose" className="block text-xs font-medium text-[#5B6B7A] mb-1">Purpose</label>
        <Input id="masking-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="e.g. csv_export" className="mb-3" />
        <div className="space-y-2 mb-3">
          {rules.map((r, i) => (
            <div key={i} className="flex gap-2 items-center">
              <Input
                value={r.field} onChange={(e) => updateRule(i, { field: e.target.value })}
                placeholder="field name" aria-label={`Field name for rule ${i + 1}`} className="flex-1"
              />
              <Select
                value={r.strategy} onChange={(e) => updateRule(i, { strategy: e.target.value })}
                aria-label={`Masking strategy for rule ${i + 1}`} className="w-40"
              >
                {STRATEGIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              <button onClick={() => setRules((prev) => prev.filter((_, idx) => idx !== i))} className="text-[#5B6B7A] hover:text-[#D6394A] p-1" aria-label="Remove field">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
        <Button variant="secondary" onClick={() => setRules((prev) => [...prev, { field: "", strategy: "allow" }])} className="mb-4">
          <Plus className="h-3.5 w-3.5" /> Add field
        </Button>
        {error && <p className="text-sm text-[#D6394A] mb-3">{error}</p>}
        <div>
          <Button onClick={handleSave} disabled={busy}>Save policy</Button>
        </div>
      </Card>
    </div>
  )
}
