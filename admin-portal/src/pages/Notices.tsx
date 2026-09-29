import { useEffect, useState } from "react"
import { Sparkles } from "lucide-react"
import { api, ApiError, type Notice } from "@/lib/api"
import { useSession } from "@/lib/useSession"
import { Card, PageHeader, Button, Badge, Input, Textarea, Loading, EmptyState } from "@/components/ui"

const LANGUAGES = ["English", "Hindi", "Kannada", "Tamil", "Telugu", "Marathi"]

export function Notices() {
  const session = useSession()
  const tenantId = session?.tenantId ?? ""
  const [language, setLanguage] = useState("English")
  const [current, setCurrent] = useState<Notice | null>(null)
  const [pendingDraft, setPendingDraft] = useState<Notice | null>(null)
  const [loading, setLoading] = useState(true)
  const [content, setContent] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // AI-assisted drafting (BRD Sec. 6.1) — structured input, not free text
  const [purpose, setPurpose] = useState("")
  const [categories, setCategories] = useState("")

  function load() {
    setLoading(true)
    setPendingDraft(null) // a draft only exists in-memory until approved — switching language clears it, which is correct: it was never persisted as "current" anyway
    api.listNoticesCurrent(tenantId, language).then(setCurrent).finally(() => setLoading(false))
  }
  useEffect(load, [tenantId, language])

  async function handleDraft() {
    setError(null); setBusy(true)
    try {
      const draft = await api.draftNotice({ tenant_id: tenantId, language, content })
      setPendingDraft(draft)
      setContent("")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the draft.")
    } finally { setBusy(false) }
  }

  async function handleAiDraft() {
    setError(null); setBusy(true)
    try {
      const draft = await api.draftNoticeAI({
        tenant_id: tenantId, language,
        purposes: [{ purpose, data_categories: categories.split(",").map((c) => c.trim()).filter(Boolean) }],
      })
      setPendingDraft(draft)
      setPurpose(""); setCategories("")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate a draft.")
    } finally { setBusy(false) }
  }

  async function handleApprove() {
    if (!pendingDraft) return
    setBusy(true)
    try {
      await api.approveNotice(pendingDraft.id, session?.email ?? "dpo")
      setPendingDraft(null)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve.")
    } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader title="Privacy Notices" subtitle="§5 — every consent request must be preceded by an approved notice, per language." />

      <div className="flex gap-2 mb-5">
        {LANGUAGES.map((l) => (
          <button
            key={l} onClick={() => setLanguage(l)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${language === l ? "bg-[#1d79c3] text-white" : "bg-[#ECEFF1] text-[#5B6B7A] hover:bg-[#dfe4e7]"}`}
          >
            {l}
          </button>
        ))}
      </div>

      {loading ? <Loading /> : (
        <Card className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#0B2A42]">Current approved notice ({language})</h2>
            {current && <Badge tone="success">v{current.version} · approved</Badge>}
          </div>
          {current ? (
            <p className="text-sm text-[#5B6B7A] whitespace-pre-line">{current.content}</p>
          ) : (
            <EmptyState title="No approved notice yet" description="Draft one below, then approve it — consent capture is blocked until then." />
          )}
        </Card>
      )}

      {pendingDraft && (
        <Card className="mb-5 border-[#1E88E5]/40 bg-[#1E88E5]/5">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#0B2A42]">Pending draft — v{pendingDraft.version}</h2>
            <Badge tone="info">awaiting approval</Badge>
          </div>
          <p className="text-sm text-[#5B6B7A] whitespace-pre-line mb-3">{pendingDraft.content}</p>
          <Button onClick={handleApprove} disabled={busy}>Approve as DPO</Button>
        </Card>
      )}

      {error && <p className="text-sm text-[#D6394A] mb-3">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <h2 className="text-sm font-semibold text-[#0B2A42] mb-3">Draft manually</h2>
          <Textarea
            rows={5} value={content} onChange={(e) => setContent(e.target.value)}
            placeholder="We collect your PAN to verify your identity for..." aria-label="Manual notice draft content" className="mb-3"
          />
          <Button onClick={handleDraft} disabled={busy || !content}>Save draft</Button>
        </Card>
        <Card>
          <div className="flex items-center gap-1.5 mb-3">
            <Sparkles className="h-4 w-4 text-[#26A69A]" />
            <h2 className="text-sm font-semibold text-[#0B2A42]">AI-assisted draft (BRD Sec. 6.1)</h2>
          </div>
          <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Purpose — e.g. KYC & loan processing" aria-label="Purpose" className="mb-2" />
          <Input value={categories} onChange={(e) => setCategories(e.target.value)} placeholder="Data categories, comma-separated — e.g. PAN, Address Proof" aria-label="Data categories, comma-separated" className="mb-3" />
          <Button variant="secondary" onClick={handleAiDraft} disabled={busy || !purpose || !categories}>Generate draft</Button>
          <p className="text-xs text-[#5B6B7A] mt-2">Structured assembly, not free-text paraphrasing — still needs your approval above.</p>
        </Card>
      </div>
    </div>
  )
}
