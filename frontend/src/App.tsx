import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { ChecksPage } from "./pages/ChecksPage";
import { RunsPage } from "./pages/RunsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { DebugPage } from "./pages/DebugPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/ui-checks" element={<ChecksPage type="ui" />} />
        <Route path="/api-checks" element={<ChecksPage type="api" />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/debug/:type/:checkId" element={<DebugPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
