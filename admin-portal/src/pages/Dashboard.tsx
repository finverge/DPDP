import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, FileText, MessageSquareWarning, ShieldCheck, TrendingUp } from "lucide-react"
import { api, type Tenant, type BreachRisk, type Usage } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, StatTile, PageHeader, Loading } from "@/components/ui"

export function Dashboard() {
  const session = useSession()
  const tenantId = session?.tenantId ?? null
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [risk, setRisk] = useState<BreachRisk | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tenantId) { setLoading(false); return }
    Promise.all([api.getTenant(tenantId), api.getBreachRisk(tenantId), api.getUsage(tenantId)])
      .then(([t, r, u]) => { setTenant(t); setRisk(r); setUsage(u) })
      .finally(() => setLoading(false))
  }, [tenantId])

  if (!tenantId) {
    return (
      <div>
        <PageHeader title="Dashboard" subtitle="Platform admin — pick a tenant to manage from the tenant registry." />
        <Card><p className="text-sm text-[#5B6B7A]">No tenant-scoped view for platform_admin yet — this account can act across tenants via the API, but the dashboard is per-tenant today.</p></Card>
      </div>
    )
  }

  if (loading) return <Loading />

  const bandColor = risk?.band === "high" ? "text-[#D6394A]" : risk?.band === "medium" ? "text-[#9c6916]" : "text-[#1f847a]"
  const totalUsage = usage ? Object.values(usage.counts).reduce((a, b) => a + b, 0) : 0

  return (
    <div>
      <PageHeader title={tenant?.name ?? "Dashboard"} subtitle={`Plan: ${tenant?.plan ?? "—"} · Tenant ID: ${tenantId}`} />

      <div className="grid grid-cols-3 gap-4 mb-6">
        <StatTile icon={AlertTriangle} label="Breach-risk score" value={String(risk?.score ?? 0)} sub={<span className={bandColor}>{risk?.band ?? "low"} band</span>} />
        <StatTile icon={TrendingUp} label="API calls (30d)" value={String(totalUsage)} sub="consent + masking + grievance events" />
        <StatTile icon={ShieldCheck} label="Drift flags contributing" value={String(risk?.factors.drift_flags ?? 0)} sub={`${risk?.factors.masking_blocks ?? 0} masking blocks`} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <div className="flex items-center gap-2 mb-3">
            <FileText className="h-4 w-4 text-[#1E88E5]" />
            <h2 className="text-sm font-semibold text-[#0B2A42]">Quick links</h2>
          </div>
          <div className="space-y-2 text-sm">
            <Link to="/notices" className="block text-[#1d79c3] hover:underline">Manage privacy notices →</Link>
            <Link to="/masking" className="block text-[#1d79c3] hover:underline">Configure masking policies →</Link>
            <Link to="/grievances" className="block text-[#1d79c3] hover:underline">Review grievances →</Link>
            <Link to="/settings" className="block text-[#1d79c3] hover:underline">Set up DPO contact & branding →</Link>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-2 mb-3">
            <MessageSquareWarning className="h-4 w-4 text-[#1E88E5]" />
            <h2 className="text-sm font-semibold text-[#0B2A42]">Usage breakdown</h2>
          </div>
          {usage && Object.keys(usage.counts).length > 0 ? (
            <ul className="text-sm space-y-1.5">
              {Object.entries(usage.counts).map(([k, v]) => (
                <li key={k} className="flex justify-between text-[#5B6B7A]">
                  <span>{k}</span><span className="font-medium text-[#0B2A42]">{v}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[#5B6B7A]">No usage recorded in the last 30 days.</p>
          )}
        </Card>
      </div>
    </div>
  )
}
