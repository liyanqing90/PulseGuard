import { Activity, History, LayoutDashboard, MonitorCheck, PlugZap, Settings } from "lucide-react";
import { Menu } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const navItems = [
  { key: "/", label: "总览", icon: <LayoutDashboard size={18} /> },
  { key: "/ui-checks", label: "UI 监控", icon: <MonitorCheck size={18} /> },
  { key: "/api-checks", label: "接口监控", icon: <PlugZap size={18} /> },
  { key: "/runs", label: "执行历史", icon: <History size={18} /> },
  { key: "/settings", label: "系统设置", icon: <Settings size={18} /> }
];

const titles: Record<string, string> = {
  "/": "总览",
  "/ui-checks": "UI 监控",
  "/api-checks": "接口监控",
  "/runs": "执行历史",
  "/settings": "系统设置"
};

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedKey = navItems.find((item) => item.key !== "/" && location.pathname.startsWith(item.key))?.key || "/";
  const activeTitle = location.pathname.startsWith("/debug")
    ? "全屏调试"
    : titles[selectedKey] || (location.pathname.startsWith("/runs") ? "执行历史" : "PulseGuard");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={18} />
          </div>
          <div>
            <div className="brand-name">PulseGuard</div>
            <div className="brand-subtitle">脉守</div>
          </div>
        </div>
        <Menu
          className="nav-menu"
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={navItems}
          onClick={({ key }) => navigate(key)}
        />
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div>
            <h1>{activeTitle}</h1>
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
