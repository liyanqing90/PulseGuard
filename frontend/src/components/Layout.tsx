import { Menu, Typography } from "antd";
import { History, LayoutDashboard, MonitorCheck, PlugZap, ScrollText, Settings, ShieldCheck } from "lucide-react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Text, Title } = Typography;

const navItems = [
  { to: "/", label: "总览", icon: <LayoutDashboard size={16} /> },
  { to: "/ui-checks", label: "UI 监控", icon: <MonitorCheck size={16} /> },
  { to: "/api-checks", label: "接口监控", icon: <PlugZap size={16} /> },
  { to: "/runs", label: "执行历史", icon: <History size={16} /> },
  { to: "/status", label: "内网状态", icon: <ShieldCheck size={16} /> },
  { to: "/operations", label: "运维审计", icon: <ScrollText size={16} /> },
  { to: "/settings", label: "系统设置", icon: <Settings size={16} /> }
];

const titles: Record<string, string> = {
  "/": "总览",
  "/ui-checks": "UI 监控",
  "/api-checks": "接口监控",
  "/runs": "执行历史",
  "/status": "内网状态",
  "/operations": "运维审计",
  "/settings": "系统设置"
};

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedPath = navItems.find((item) => item.to !== "/" && location.pathname.startsWith(item.to))?.to || "/";
  const activeTitle = location.pathname.startsWith("/debug")
    ? "全屏调试"
    : titles[selectedPath] || (location.pathname.startsWith("/runs") ? "执行历史" : "PulseGuard");

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
          <div className="runtime-pill">
            <span className="runtime-dot" />
            本地运行
          </div>
        </header>
        <Outlet />
      </main>
    </div>
  );
}
