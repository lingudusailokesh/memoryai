import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

// UI guard only. The real protection is the backend rejecting requests without a valid token.
export default function ProtectedRoute() {
  const { status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <div className="grid min-h-screen place-items-center text-mute">Loading your session…</div>;
  if (status === "anon") return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <Outlet />;
}
