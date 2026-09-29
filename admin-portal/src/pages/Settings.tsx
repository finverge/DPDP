import { useEffect, useState } from "react"
import { KeyRound } from "lucide-react"
import { api, ApiError, type Tenant } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Input, Loading, Badge } from "@/components/ui"

export function Settings() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const [dpoName, setDpoName] = useState("")
  const [dpoEmail, setDpoEmail] = useState("")
  const [dpoPhone, setDpoPhone] = useState("")

  const [primaryColor, setPrimaryColor] = useState("")
  const [logoUrl, setLogoUrl] = useState("")
  const [fontFamily, setFontFamily] = useState("")

  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [revealedKey, setRevealedKey] = useState<string | null>(null)

  function loadTenant() {
    return api.getTenant(tenantId).then((t) => {
      setTenant(t)
      setPrimaryColor(t.brand_primary_color ?? "")
      setLogoUrl(t.brand_logo_url ?? "")
      setFontFamily(t.brand_font_family ?? "")
    })
  }

  useEffect(() => {
    Promise.all([api.getDpoContact(tenantId), loadTenant()]).then(([dpo]) => {
      if (dpo) { setDpoName(dpo.name); setDpoEmail(dpo.email); setDpoPhone(dpo.phone ?? "") }
    }).finally(() => setLoading(false))
  }, [tenantId])

  async function handleRotateApiKey() {
    setError(null); setBusy(true)
    try {
      const rotated = await api.rotateApiKey(tenantId)
      setRevealedKey(rotated.api_key)
      await loadTenant()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rotate the API key.")
    } finally { setBusy(false) }
  }

  async function handleSaveDpo() {
    setError(null); setBusy(true); setSaved(false)
    try {
      await api.upsertDpoContact({ tenant_id: tenantId, name: dpoName, email: dpoEmail, phone: dpoPhone || undefined })
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the DPO contact.")
    } finally { setBusy(false) }
  }

  async function handleSaveBranding() {
    setError(null); setBusy(true); setSaved(false)
    try {
      await api.updateBranding(tenantId, {
        brand_primary_color: primaryColor || undefined,
        brand_logo_url: logoUrl || undefined,
        brand_font_family: fontFamily || undefined,
      })
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save branding.")
    } finally { setBusy(false) }
  }

  if (loading) return <Loading />

  return (
    <div>
      <PageHeader title="DPO & Branding" subtitle="§8(9)-(10) grievance-officer publication, and the white-label settings the SDK widget's autoTheme reads." />

      {error && <p className="text-sm text-[#D6394A] mb-4">{error}</p>}
      {saved && <p className="text-sm text-[#1f847a] mb-4">Saved.</p>}

      {revealedKey && (
        <Card className="mb-5 bg-[#E0A030]/10 border-[#E0A030]/40">
          <p className="text-xs font-medium text-[#0B2A42] mb-1">New API key — shown once, save it now:</p>
          <code className="block text-xs bg-white rounded-lg px-3 py-2 break-all border border-[#E2E5EA]">{revealedKey}</code>
          <p className="text-xs text-[#5B6B7A] mt-2">The previous key keeps working for 48 hours so any in-flight integration has time to switch over.</p>
          <button onClick={() => setRevealedKey(null)} className="text-xs text-[#5B6B7A] hover:text-[#0B2A42] mt-2">Dismiss</button>
        </Card>
      )}

      <Card className="mb-5">
        <div className="flex items-center gap-1.5 mb-3">
          <KeyRound className="h-4 w-4 text-[#1d79c3]" />
          <h2 className="text-sm font-semibold text-[#0B2A42]">API Key</h2>
        </div>
        {tenant && (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <code className="bg-[#ECEFF1] px-2 py-1 rounded text-xs">{tenant.api_key_prefix}…</code>
              <span className="text-xs text-[#5B6B7A]">issued {new Date(tenant.api_key_created_at).toLocaleDateString()}</span>
            </div>
            <p className="text-xs text-[#5B6B7A]">
              Scheduled to auto-rotate by {new Date(tenant.api_key_rotate_by).toLocaleDateString()} — hashed at rest, never stored or shown again after creation/rotation.
            </p>
            {tenant.previous_api_key_expires_at && (
              <p className="text-xs">
                <Badge tone="warning">grace period</Badge>{" "}
                <span className="text-[#5B6B7A]">previous key still valid until {new Date(tenant.previous_api_key_expires_at).toLocaleString()}</span>
              </p>
            )}
            <Button variant="secondary" onClick={handleRotateApiKey} disabled={busy} className="mt-1">Rotate now</Button>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Grievance Officer / DPO Contact</h2>
          <div className="space-y-3">
            <div>
              <label htmlFor="dpo-name" className="block text-xs font-medium text-[#5B6B7A] mb-1">Name</label>
              <Input id="dpo-name" value={dpoName} onChange={(e) => setDpoName(e.target.value)} />
            </div>
            <div>
              <label htmlFor="dpo-email" className="block text-xs font-medium text-[#5B6B7A] mb-1">Email</label>
              <Input id="dpo-email" type="email" value={dpoEmail} onChange={(e) => setDpoEmail(e.target.value)} />
            </div>
            <div>
              <label htmlFor="dpo-phone" className="block text-xs font-medium text-[#5B6B7A] mb-1">Phone (optional)</label>
              <Input id="dpo-phone" value={dpoPhone} onChange={(e) => setDpoPhone(e.target.value)} />
            </div>
            <Button onClick={handleSaveDpo} disabled={busy || !dpoName || !dpoEmail}>Save DPO contact</Button>
          </div>
        </Card>

        <Card>
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">White-Label Branding</h2>
          <div className="space-y-3">
            <div>
              <label htmlFor="brand-primary-color" className="block text-xs font-medium text-[#5B6B7A] mb-1">Primary color</label>
              <div className="flex items-center gap-2">
                <Input id="brand-primary-color" value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} placeholder="#1E88E5" />
                {primaryColor && <span className="h-8 w-8 rounded-md border border-[#E2E5EA] shrink-0" style={{ background: primaryColor }} />}
              </div>
            </div>
            <div>
              <label htmlFor="brand-logo-url" className="block text-xs font-medium text-[#5B6B7A] mb-1">Logo URL</label>
              <Input id="brand-logo-url" value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://yourcompany.example/logo.png" />
            </div>
            <div>
              <label htmlFor="brand-font-family" className="block text-xs font-medium text-[#5B6B7A] mb-1">Font family</label>
              <Input id="brand-font-family" value={fontFamily} onChange={(e) => setFontFamily(e.target.value)} placeholder="Inter, sans-serif" />
            </div>
            <Button onClick={handleSaveBranding} disabled={busy}>Save branding</Button>
            <p className="text-xs text-[#5B6B7A]">Picked up automatically by the SDK widget when <code className="bg-[#ECEFF1] px-1 rounded">autoTheme: true</code> is set.</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
