import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { Layout } from "@/components/Layout"
import { Login } from "@/pages/Login"
import { GetStarted } from "@/pages/GetStarted"
import { Dashboard } from "@/pages/Dashboard"
import { Notices } from "@/pages/Notices"
import { MaskingPolicies } from "@/pages/MaskingPolicies"
import { Grievances } from "@/pages/Grievances"
import { Webhooks } from "@/pages/Webhooks"
import { AIInsights } from "@/pages/AIInsights"
import { RegulatoryWatch } from "@/pages/RegulatoryWatch"
import { Settings } from "@/pages/Settings"
import { getToken } from "@/lib/api"

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/get-started" element={<GetStarted />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="notices" element={<Notices />} />
          <Route path="masking" element={<MaskingPolicies />} />
          <Route path="grievances" element={<Grievances />} />
          <Route path="webhooks" element={<Webhooks />} />
          <Route path="ai-insights" element={<AIInsights />} />
          <Route path="regulatory-watch" element={<RegulatoryWatch />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
