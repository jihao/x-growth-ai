import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileText,
  History,
  Home,
  LineChart,
  PieChart,
  RefreshCcw,
  Target,
  UserCircle,
  Users
} from "lucide-react";
import type { ReactNode } from "react";
import { pageTitle, type Page } from "../appTypes";
import type { AppUser } from "../types";

const navItems: Array<{ id: Page; label: string; icon: typeof Home }> = [
  { id: "home", label: "首页", icon: Home },
  { id: "screen", label: "选股", icon: Target },
  { id: "stock", label: "个股", icon: LineChart },
  { id: "strategy", label: "策略", icon: BarChart3 },
  { id: "concentration", label: "集中度", icon: PieChart },
  { id: "reports", label: "日报", icon: FileText },
  { id: "history", label: "历史", icon: History },
  { id: "learning", label: "学习", icon: BookOpen },
  { id: "data", label: "数据", icon: Database },
  { id: "users", label: "用户", icon: Users }
];

export function AppShell({
  page,
  error,
  loading,
  children,
  user,
  onPageChange,
  onRefresh,
  onLogout
}: {
  page: Page;
  error: string | null;
  loading: boolean;
  children: ReactNode;
  user: AppUser;
  onPageChange: (page: Page) => void;
  onRefresh: () => void;
  onLogout: () => void;
}) {
  const visibleNav = user.role === "admin" ? navItems : navItems.filter((item) => item.id !== "users");
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Activity size={22} />
          <div>
            <strong>X-Growth AI</strong>
            <span>交易研究工作台</span>
          </div>
        </div>
        <nav>
          {visibleNav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => onPageChange(item.id)}>
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <h1>{pageTitle(page)}</h1>
            <p>Ant Design Pro 风格工作台 · SQLite 本地数据</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={onRefresh} title="刷新数据">
              <RefreshCcw size={18} />
              刷新
            </button>
            <button className="account-button" onClick={() => onPageChange("users")} title="账户中心">
              <UserCircle size={18} />
              <span>{user.display_name || user.username}</span>
              <small>{user.role === "admin" ? "管理员" : "用户"}</small>
            </button>
            <button className="icon-button" onClick={onLogout}>退出</button>
          </div>
        </header>
        {error && <div className="alert">{error}</div>}
        {loading && <div className="loading">正在读取本地数据库...</div>}
        {children}
      </main>
    </div>
  );
}
