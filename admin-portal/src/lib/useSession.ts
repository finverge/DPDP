import { useState, useEffect } from "react"
import { getSession, type Session } from "./api"

/** Re-reads localStorage on mount and on the "cb-session-changed" event
 * login/logout dispatch, so every component sees the same session without
 * a full page reload. */
export function useSession(): Session | null {
  const [session, setSessionState] = useState<Session | null>(getSession())
  useEffect(() => {
    const handler = () => setSessionState(getSession())
    window.addEventListener("cb-session-changed", handler)
    return () => window.removeEventListener("cb-session-changed", handler)
  }, [])
  return session
}
