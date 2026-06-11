import { Skeleton } from "antd";
import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";

const OverviewPage = lazy(() => import("./pages/OverviewPage").then((module) => ({ default: module.OverviewPage })));
const ChecksPage = lazy(() => import("./pages/ChecksPage").then((module) => ({ default: module.ChecksPage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then((module) => ({ default: module.RunsPage })));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage").then((module) => ({ default: module.RunDetailPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const MembersPage = lazy(() => import("./pages/MembersPage").then((module) => ({ default: module.MembersPage })));
const DebugPage = lazy(() => import("./pages/DebugPage").then((module) => ({ default: module.DebugPage })));
const OperationsPage = lazy(() => import("./pages/OperationsPage").then((module) => ({ default: module.OperationsPage })));

function page(element: ReactNode) {
  return <Suspense fallback={<RouteLoading />}>{element}</Suspense>;
}

function RouteLoading() {
  return (
    <div className="page-content">
      <Skeleton active paragraph={{ rows: 8 }} />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={page(<OverviewPage />)} />
        <Route path="/ui-checks" element={page(<ChecksPage type="ui" />)} />
        <Route path="/api-checks" element={page(<ChecksPage type="api" />)} />
        <Route path="/runs" element={page(<RunsPage />)} />
        <Route path="/runs/:runId" element={page(<RunDetailPage />)} />
        <Route path="/operations" element={page(<OperationsPage />)} />
        <Route path="/settings" element={<Navigate to="/settings/execution" replace />} />
        <Route path="/settings/:tab" element={page(<SettingsPage />)} />
        <Route path="/members" element={page(<MembersPage />)} />
        <Route path="/debug/:type/:checkId" element={page(<DebugPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
