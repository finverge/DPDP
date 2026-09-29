import type { ReactNode } from "react"
import { Loader2 } from "lucide-react"
import type { LucideIcon } from "lucide-react"

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0B2A42] tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-[#5B6B7A] mt-1">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`bg-white rounded-xl border border-[#E2E5EA] p-5 ${className}`}>{children}</div>
}

export function StatTile({ icon: Icon, label, value, sub }: { icon: LucideIcon; label: string; value: string; sub?: ReactNode }) {
  return (
    <Card>
      <div className="flex items-center gap-2 text-[#5B6B7A] text-xs font-medium mb-2">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className="text-3xl font-semibold text-[#0B2A42]">{value}</div>
      {sub && <div className="text-xs text-[#5B6B7A] mt-1">{sub}</div>}
    </Card>
  )
}

export function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-[#5B6B7A] py-10 justify-center">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading…
    </div>
  )
}

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "success" | "warning" | "danger" | "info" }) {
  const tones: Record<string, string> = {
    muted: "bg-[#ECEFF1] text-[#5B6B7A]",
    success: "bg-[#26A69A]/15 text-[#166b62]",
    warning: "bg-[#E0A030]/15 text-[#8a6318]",
    danger: "bg-[#D6394A]/15 text-[#a12335]",
    info: "bg-[#1E88E5]/15 text-[#14609e]",
  }
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${tones[tone]}`}>{children}</span>
}

export function Button({
  children, onClick, variant = "primary", type = "button", disabled, className = "",
}: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "ghost"
  type?: "button" | "submit"; disabled?: boolean; className?: string
}) {
  const variants: Record<string, string> = {
    primary: "bg-[#1d79c3] text-white hover:bg-[#1a6cae]",
    secondary: "bg-[#ECEFF1] text-[#0B2A42] hover:bg-[#dfe4e7]",
    danger: "bg-[#D6394A] text-white hover:bg-[#bd2f3f]",
    ghost: "text-[#1d79c3] hover:bg-[#1E88E5]/10",
  }
  return (
    <button
      type={type} onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="text-center py-10 text-[#5B6B7A]">
      <p className="text-sm font-medium text-[#0B2A42]">{title}</p>
      {description && <p className="text-xs mt-1">{description}</p>}
    </div>
  )
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5] ${props.className ?? ""}`}
    />
  )
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5] ${props.className ?? ""}`}
    />
  )
}

export function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`w-full rounded-lg border border-[#E2E5EA] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E88E5]/30 focus:border-[#1E88E5] bg-white ${props.className ?? ""}`}
    >
      {children}
    </select>
  )
}
