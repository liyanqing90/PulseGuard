import { Button, Menu, Modal, Typography } from "antd";
import { History, LayoutDashboard, Megaphone, MonitorCheck, PlugZap, ScrollText, Settings, ShieldCheck, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { StatusPageSnapshot } from "../types";
import { formatDate } from "../utils";

const { Text, Title } = Typography;

const navItems = [
  { to: "/", label: "总览", icon: <LayoutDashboard size={16} /> },
  { to: "/ui-checks", label: "页面监控", icon: <MonitorCheck size={16} /> },
  { to: "/api-checks", label: "接口监控", icon: <PlugZap size={16} /> },
  { to: "/runs", label: "运行记录", icon: <History size={16} /> },
  { to: "/status", label: "内网状态", icon: <ShieldCheck size={16} /> },
  { to: "/operations", label: "运维审计", icon: <ScrollText size={16} /> },
  { to: "/members", label: "成员管理", icon: <Users size={16} /> },
  { to: "/settings", label: "系统设置", icon: <Settings size={16} /> }
];

const titles: Record<string, string> = {
  "/": "总览",
  "/ui-checks": "页面监控",
  "/api-checks": "接口监控",
  "/runs": "运行记录",
  "/members": "成员管理",
  "/status": "内网状态",
  "/operations": "运维审计",
  "/settings": "系统设置"
};

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [maintenance, setMaintenance] = useState<StatusPageSnapshot["maintenance"] | null>(null);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const selectedPath = navItems.find((item) => item.to !== "/" && location.pathname.startsWith(item.to))?.to || "/";
  const activeTitle = location.pathname.startsWith("/debug")
    ? "全屏调试"
    : titles[selectedPath] || (location.pathname.startsWith("/runs") ? "运行记录" : "PulseGuard");
  const maintenanceWindow = formatMaintenanceWindow(maintenance?.starts_at, maintenance?.ends_at);
  const showMaintenanceButton = Boolean(maintenance?.enabled);

  useEffect(() => {
    let disposed = false;
    const loadMaintenance = () => {
      api
        .statusPage()
        .then((snapshot) => {
          if (!disposed) setMaintenance(snapshot.maintenance);
        })
        .catch(() => {
          if (!disposed) setMaintenance(null);
        });
    };
    loadMaintenance();
    window.addEventListener("pulseguard:maintenance-updated", loadMaintenance);
    return () => {
      disposed = true;
      window.removeEventListener("pulseguard:maintenance-updated", loadMaintenance);
    };
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <div className="brand-mark">
            <img src="/favicon.svg" alt="" aria-hidden="true" />
          </div>
          <div>
            <Text strong className="brand-name">
              PulseGuard
            </Text>
            <Text type="secondary" className="brand-subtitle">
              探测控制台
            </Text>
          </div>
        </div>
        <Menu
          className="nav-menu"
          mode="inline"
          selectedKeys={[selectedPath]}
          items={navItems.map((item) => ({ key: item.to, icon: item.icon, label: item.label }))}
          onClick={({ key }) => navigate(key)}
        />
      </aside>
      <main className="main-area" id="main-content">
        <header className="topbar">
          <div>
            <Title level={1} className="page-title">
              {activeTitle}
            </Title>
          </div>
          <div className="topbar-actions">
            {showMaintenanceButton && (
              <Button className="maintenance-topbar-button" icon={<Megaphone size={15} />} onClick={() => setMaintenanceOpen(true)}>
                公告
              </Button>
            )}
            <div className="runtime-pill">
              <span className="runtime-dot" />
              本地运行
            </div>
          </div>
        </header>
        <Outlet />
      </main>
      <Modal
        title={maintenance?.title || "维护公告"}
        open={maintenanceOpen}
        footer={null}
        onCancel={() => setMaintenanceOpen(false)}
      >
        <div className="maintenance-modal-content">
          <p>{maintenance?.message || "暂无公告内容"}</p>
          {maintenanceWindow && (
            <div className="maintenance-window">
              <span>维护窗口</span>
              <strong>{maintenanceWindow}</strong>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}

function formatMaintenanceWindow(startsAt?: string, endsAt?: string): string {
  const start = startsAt ? formatDate(startsAt) : "";
  const end = endsAt ? formatDate(endsAt) : "";
  if (start && end) return `${start} - ${end}`;
  return start || end;
}
