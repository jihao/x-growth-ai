import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileText,
  Home,
  LineChart,
  PieChart,
  RefreshCcw,
  Target
} from "lucide-react";
import type { ReactNode } from "react";
import { pageTitle, type Page } from "../appTypes";

const navItems: Array<{ id: Page; label: string; icon: typeof Home }> = [
  { id: "home", label: "首页", icon: Home },
  { id: "screen", label: "选股", icon: Target },
  { id: "stock", label: "个股", icon: LineChart },
  { id: "strategy", label: "策略", icon: BarChart3 },
  { id: "concentration", label: "集中度", icon: PieChart },
  { id: "reports", label: "日报", icon: FileText },
  { id: "learning", label: "学习", icon: BookOpen },
  { id: "data", label: "数据", icon: Database }
];

export function AppShell({
  page,
  error,
  loading,
  children,
  onPageChange,
  onRefresh
}: {
  page: Page;
  error: string | null;
  loading: boolean;
  children: ReactNode;
  onPageChange: (page: Page) => void;
  onRefresh: () => void;
}) {
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
          {navItems.map((item) => {
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
          </div>
          <button className="icon-button" onClick={onRefresh} title="刷新数据">
            <RefreshCcw size={18} />
            刷新
          </button>
        </header>
        {error && <div className="alert">{error}</div>}
        {loading && <div className="loading">正在读取本地数据库...</div>}
        {children}
      </main>
    </div>
  );
}
