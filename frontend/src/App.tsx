import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import AssemblyPage from './pages/AssemblyPage';
import MarketplacesPage from './pages/MarketplacesPage';
import UsersPage from './pages/UsersPage';
import PrintSettingsPage from './pages/PrintSettingsPage';
import AccountPage from './pages/AccountPage';
import AppLayout from './components/layout/AppLayout';
import ProtectedRoute from './components/layout/ProtectedRoute';

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/assembly" replace />} />
        <Route path="assembly" element={<AssemblyPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="marketplaces" element={<MarketplacesPage />} />
        <Route path="print-settings" element={<PrintSettingsPage />} />
        <Route path="users" element={<UsersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
