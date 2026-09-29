import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import { ShieldHalf, Loader2 } from "lucide-react"
import { api, setSession, ApiError } from "@/lib/api"

export function Login() {
  const navigate = useNavigate()
  const [tenantId, setTenantId] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await api.login({ tenant_id: tenantId || null, email, password })
      setSession(result.access_token, { role: result.role, tenantId: result.tenant_id, email })
      window.dispatchEvent(new Event("cb-session-changed"))
      navigate("/")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not log in. Please try again.")
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
        <h1 className="text-xl font-semibold text-[#0B2A42] mb-1">Admin sign in</h1>
        <p className="text-sm text-[#5B6B7A] mb-6">Manage notices, masking policies, and grievances for your tenant.</p>

        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label htmlFor="login-tenant-id" className="block text-xs font-medium text-[#5B6B7A] mb-1">Tenant ID (leave blank for platform admin)</label>
            <input
              id="login-tenant-id"
              value={tenantId} onChange={(e) => setTenantId(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
              placeholder="e.g. a353d07c-..."
            />
          </div>
          <div>
            <label htmlFor="login-email" className="block text-xs font-medium text-[#5B6B7A] mb-1">Email</label>
            <input
              id="login-email"
              type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
            />
          </div>
          <div>
            <label htmlFor="login-password" className="block text-xs font-medium text-[#5B6B7A] mb-1">Password</label>
            <input
              id="login-password"
              type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5]"
            />
          </div>
          {error && <p className="text-sm text-[#D6394A]">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full flex items-center justify-center gap-2 rounded-lg bg-[#1d79c3] text-white text-sm font-medium py-2.5 hover:bg-[#1a6cae] transition-colors disabled:opacity-60"
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            Sign in
          </button>
        </form>

        <p className="text-xs text-[#5B6B7A] mt-5 text-center">
          New tenant? <Link to="/get-started" className="text-[#1d79c3] font-medium hover:underline">Get started</Link>
        </p>
      </div>
    </div>
  )
}
