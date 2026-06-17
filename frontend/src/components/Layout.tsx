import { Button, Dropdown, Menu, Modal, Typography } from "antd";
import type { MenuProps } from "antd";
import {
  Activity,
  BellRing,
  History,
  KeyRound,
  LayoutDashboard,
  Megaphone,
  MonitorCheck,
  MoreHorizontal,
  PlugZap,
  ScrollText,
  Settings,
  Users
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Button as UiButton } from "./ui/button";
import type { StatusPageSnapshot } from "../types";
import { formatDate } from "../utils";

const { Text, Title } = Typography;
const APP_TEAM_NAME = "新零售测试团队";

type NavLeaf = {
  to: string;
  label: string;
  icon: ReactNode;
};

type NavEntry =
  | NavLeaf
  | {
      key: string;
      label: string;
      icon: ReactNode;
      children: NavLeaf[];
    };

const navEntries: NavEntry[] = [
  { to: "/", label: "总览", icon: <LayoutDashboard size={16} /> },
  {
    key: "monitoring",
    label: "监控任务",
    icon: <MonitorCheck size={16} />,
    children: [
      { to: "/ui-checks", label: "页面监控", icon: <MonitorCheck size={16} /> },
      { to: "/api-checks", label: "接口监控", icon: <PlugZap size={16} /> },
      { to: "/monitoring", label: "监控趋势", icon: <Activity size={16} /> }
    ]
  },
  { to: "/runs", label: "运行记录", icon: <History size={16} /> },
  { to: "/members", label: "成员管理", icon: <Users size={16} /> },
  {
    key: "system",
    label: "系统设置",
    icon: <Settings size={16} />,
    children: [
      { to: "/settings/execution", label: "执行配置", icon: <Activity size={16} /> },
      { to: "/settings/alerts", label: "告警配置", icon: <BellRing size={16} /> },
      { to: "/settings/variables", label: "变量管理", icon: <KeyRound size={16} /> },
      { to: "/settings/system", label: "系统配置", icon: <Settings size={16} /> },
      { to: "/operations", label: "运维审计", icon: <ScrollText size={16} /> }
    ]
  }
];

const navItems = navEntries.flatMap((entry) => ("to" in entry ? [entry] : entry.children));

const menuItems: MenuProps["items"] = navEntries.map((entry) => {
  if ("to" in entry) {
    return { key: entry.to, icon: entry.icon, label: entry.label };
  }
  return {
    key: entry.key,
    icon: entry.icon,
    label: entry.label,
    children: entry.children.map((item) => ({ key: item.to, icon: item.icon, label: item.label }))
  };
});

const defaultOpenKeys = navEntries.flatMap((entry) => ("to" in entry ? [] : [entry.key]));

const mobilePrimaryItems = [
  { to: "/", label: "总览", shortLabel: "总览", icon: <LayoutDashboard size={16} /> },
  { to: "/ui-checks", label: "页面监控", shortLabel: "页面", icon: <MonitorCheck size={16} /> },
  { to: "/api-checks", label: "接口监控", shortLabel: "接口", icon: <PlugZap size={16} /> },
  { to: "/runs", label: "运行记录", shortLabel: "记录", icon: <History size={16} /> }
];

const mobileMoreItems: NavLeaf[] = [
  { to: "/monitoring", label: "监控趋势", icon: <Activity size={16} /> },
  { to: "/members", label: "成员管理", icon: <Users size={16} /> },
  { to: "/settings/execution", label: "执行配置", icon: <Activity size={16} /> },
  { to: "/settings/alerts", label: "告警配置", icon: <BellRing size={16} /> },
  { to: "/settings/variables", label: "变量管理", icon: <KeyRound size={16} /> },
  { to: "/settings/system", label: "系统配置", icon: <Settings size={16} /> },
  { to: "/operations", label: "运维审计", icon: <ScrollText size={16} /> }
];

const titles: Record<string, string> = Object.fromEntries(navItems.map((item) => [item.to, item.label]));

function pathMatchesNavItem(pathname: string, itemPath: string): boolean {
  if (itemPath === "/") return pathname === "/";
  return pathname === itemPath || pathname.startsWith(`${itemPath}/`);
}

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [maintenance, setMaintenance] = useState<StatusPageSnapshot["maintenance"] | null>(null);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const selectedPath =
    [...navItems]
      .sort((left, right) => right.to.length - left.to.length)
      .find((item) => pathMatchesNavItem(location.pathname, item.to))?.to || "/";
  const activeTitle = location.pathname.startsWith("/debug")
    ? "全屏调试"
    : titles[selectedPath] || (location.pathname.startsWith("/runs") ? "运行记录" : "PulseGuard");
  const maintenanceWindow = formatMaintenanceWindow(maintenance?.starts_at, maintenance?.ends_at);
  const showMaintenanceButton = Boolean(maintenance?.enabled);
  const mobileMoreActive = mobileMoreItems.some((item) => pathMatchesNavItem(location.pathname, item.to));

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
          <div className="brand-copy">
            <div className="brand-title-row">
              <Text strong className="brand-name">
                PulseGuard
              </Text>
              <span className="brand-team">{APP_TEAM_NAME}</span>
            </div>
          </div>
        </div>
        <Menu
          className="nav-menu"
          mode="inline"
          inlineIndent={18}
          defaultOpenKeys={defaultOpenKeys}
          selectedKeys={[selectedPath]}
          items={menuItems}
          onClick={({ key }) => {
            const path = String(key);
            if (navItems.some((item) => item.to === path)) {
              navigate(path);
            }
          }}
        />
        <div className="mobile-nav-grid" aria-label="移动主导航">
          {mobilePrimaryItems.map((item) => {
            const active = selectedPath === item.to;
            return (
              <UiButton
                key={item.to}
                type="button"
                variant="ghost"
                size="nav"
                className={`mobile-nav-item ${active ? "is-active" : ""}`}
                aria-label={item.label}
                aria-current={active ? "page" : undefined}
                onClick={() => navigate(item.to)}
              >
                <span className="mobile-nav-item-icon">{item.icon}</span>
                <span className="mobile-nav-item-label">{item.shortLabel}</span>
              </UiButton>
            );
          })}
          <Dropdown
            trigger={["click"]}
            placement="bottomRight"
            menu={{
              items: mobileMoreItems.map((item) => ({ key: item.to, icon: item.icon, label: item.label })),
              selectedKeys: mobileMoreActive ? [selectedPath] : [],
              onClick: ({ key }) => navigate(String(key))
            }}
          >
            <UiButton
              type="button"
              variant="ghost"
              size="nav"
              className={`mobile-nav-item ${mobileMoreActive ? "is-active" : ""}`}
              aria-label="更多导航"
              aria-current={mobileMoreActive ? "page" : undefined}
            >
              <span className="mobile-nav-item-icon">
                <MoreHorizontal size={16} />
              </span>
              <span className="mobile-nav-item-label">更多</span>
            </UiButton>
          </Dropdown>
        </div>
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
