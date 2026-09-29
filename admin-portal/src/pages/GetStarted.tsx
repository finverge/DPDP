import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import { ShieldHalf, Loader2 } from "lucide-react"
import { api, setSession, ApiError } from "@/lib/api"

/** Self-service onboarding (FSD Sec. 5.1): registers a Tenant (POST
 * /tenants) then the first tenant_admin user for it (POST /auth/register)
 * — the two-step flow the backend already supports, wrapped into one form
 * so a new customer doesn't need to know the API exists. */
export function GetStarted() {
  const navigate = useNavigate()
  const [companyName, setCompanyName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const tenant = await api.createTenant({ name: companyName, plan: "trial" })
      await api.register({ tenant_id: tenant.id, email, password, role: "tenant_admin" })
      const result = await api.login({ tenant_id: tenant.id, email, password })
      setSession(result.access_token, { role: result.role, tenantId: result.tenant_id, email })
      window.dispatchEvent(new Event("cb-session-changed"))
      navigate("/")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0B2A42] px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-xl p-8">
        <div className="flex items-center gap-2 mb-6">
          <ShieldHalf className="h-7 w-7 text-[#1E88E5]" />
          <span className="text-lg font-semibold text-[#0B2A42]">ConsentBridge</span>
        </div>
        <h1 className="text-xl font-semibold text-[#0B2A42] mb-1">Get started</h1>
        <p className="text-sm text-[#5B6B7A] mb-6">Creates your tenant and your first admin account — trial plan, no card required.</p>

        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label htmlFor="getstarted-company" className="block text-xs font-medium text-[#5B6B7A] mb-1">Company / product name</label>
            <input
              id="getstarted-company"
              required value={companyName} onChange={(e) => setCompanyName(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
              placeholder="Acme Fintech"
            />
          </div>
          <div>
            <label htmlFor="getstarted-email" className="block text-xs font-medium text-[#5B6B7A] mb-1">Your email</label>
            <input
              id="getstarted-email"
              type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
            />
          </div>
          <div>
            <label htmlFor="getstarted-password" className="block text-xs font-medium text-[#5B6B7A] mb-1">Password</label>
            <input
              id="getstarted-password"
              type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
            />
            <p className="text-xs text-[#5B6B7A] mt-1">At least 8 characters.</p>
          </div>
          {error && <p className="text-sm text-[#D6394A]">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full flex items-center justify-center gap-2 rounded-lg bg-[#1f847a] text-white text-sm font-medium py-2.5 hover:bg-[#1a7069] transition-colors disabled:opacity-60"
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            Create my tenant
          </button>
        </form>

        <p className="text-xs text-[#5B6B7A] mt-5 text-center">
          Already have an account? <Link to="/login" className="text-[#1d79c3] font-medium hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
