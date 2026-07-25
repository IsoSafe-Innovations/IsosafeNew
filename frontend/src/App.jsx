import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import { useAuth } from './hooks/useAuth.jsx';
import Admin from './views/Admin.jsx';
import Alerts from './views/Alerts.jsx';
import Analytics from './views/Analytics.jsx';
import Assistant from './views/Assistant.jsx';
import Cameras from './views/Cameras.jsx';
import Dashboard from './views/Dashboard.jsx';
import Incidents from './views/Incidents.jsx';
import Investigations from './views/Investigations.jsx';
import Login from './views/Login.jsx';
import Reports from './views/Reports.jsx';

export default function App() {
  const { user } = useAuth();

  if (!user) return <Login />;

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:id" element={<Incidents />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/investigations" element={<Investigations />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
