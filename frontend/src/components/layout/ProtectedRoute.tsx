import { Navigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import type { RootState } from '../../store';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const devAuthBypass = import.meta.env.VITE_DEV_AUTH_BYPASS === '1';
  const accessToken = useSelector((state: RootState) => state.auth.accessToken);
  const location = useLocation();

  if (!devAuthBypass && !accessToken) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
