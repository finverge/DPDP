import { NavLink, Outlet, useNavigate } from "react-router-dom"
import { LayoutDashboard, FileText, ShieldCheck, MessageSquareWarning, Settings, Sparkles, LogOut, ShieldHalf, Webhook, RadioTower } from "lucide-react"
import { clearSession } from "@/lib/api"
import { useSession } from "@/lib/useSession"

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/notices", label: "Notices", icon: FileText },
  { to: "/masking", label: "Masking Policies", icon: ShieldCheck },
  { to: "/grievances", label: "Grievances", icon: MessageSquareWarning },
  { to: "/webhooks", label: "Webhooks", icon: Webhook },
  { to: "/ai-insights", label: "AI Insights", icon: Sparkles },
  { to: "/regulatory-watch", label: "Regulatory Watch", icon: RadioTower },
  { to: "/settings", label: "DPO & Branding", icon: Settings },
]

export function Layout() {
  const session = useSession()
  const navigate = useNavigate()

  function handleLogout() {
    clearSession()
    window.dispatchEvent(new Event("cb-session-changed"))
    navigate("/login")
  }

  return (
    <div className="min-h-screen flex bg-[#F7F9FB]">
      <aside className="w-60 shrink-0 bg-[#0B2A42] text-white flex flex-col">
        <div className="flex items-center gap-2 px-5 py-5">
          <ShieldHalf className="h-6 w-6 text-[#26A69A]" />
          <span className="font-semibold tracking-tight">ConsentBridge</span>
        </div>
        <nav className="flex-1 px-3 space-y-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  isActive ? "bg-white/10 text-white font-medium" : "text-white/70 hover:bg-white/5 hover:text-white"
                }`
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 pb-4 pt-2 border-t border-white/10">
          <div className="px-3 py-2 text-xs text-white/60">
            <div className="truncate">{session?.email}</div>
            <div className="text-white/60">{session?.role}{session?.tenantId ? ` · ${session.tenantId.slice(0, 8)}…` : ""}</div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-white/70 hover:bg-white/5 hover:text-white transition-colors"
          >
            <LogOut className="h-4 w-4" /> Log out
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
