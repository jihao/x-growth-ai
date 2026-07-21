import { LockKeyhole, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppUser } from "../types";
import { EmptyState, PanelTitle } from "./ui/Panel";

export function AuthPage({ onAuthenticated }: { onAuthenticated: (user: AppUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("admin");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("admin123");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>("默认管理员：admin / admin123，首次登录后请修改密码。");

  async function submit() {
    setLoading(true);
    setMessage(null);
    try {
      if (mode === "register") {
        await api.register({ username, password, display_name: displayName });
      }
      const payload = await api.login({ username, password });
      onAuthenticated(payload.user);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "认证失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-hero">
        <div className="auth-hero-copy">
          <span>X-Growth AI</span>
          <h1>交易研究工作台</h1>
          <p>登录后进入选股、个股分析、策略验证、日报复盘和学习资料。账户数据保存在本地 SQLite。</p>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-tabs">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
            <LockKeyhole size={16} /> 登录
          </button>
          <button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>
            <UserPlus size={16} /> 注册
          </button>
        </div>
        <label className="form-field">
          <span>用户名</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </label>
        {mode === "register" && (
          <label className="form-field">
            <span>显示名称</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
        )}
        <label className="form-field">
          <span>密码</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>
        {message && <div className={message.includes("失败") || message.includes("错误") ? "alert" : "auth-note"}>{message}</div>}
        <button className="primary-button" onClick={submit} disabled={loading}>
          <ShieldCheck size={16} /> {loading ? "处理中..." : mode === "login" ? "登录" : "注册并登录"}
        </button>
      </section>
    </main>
  );
}

export function UserManagementPage({ currentUser }: { currentUser: AppUser }) {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function loadUsers() {
    if (currentUser.role !== "admin") return;
    setLoading(true);
    setMessage(null);
    try {
      setUsers(await api.users());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "用户列表加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, [currentUser.id, currentUser.role]);

  async function saveUser(user: AppUser, patch: Partial<AppUser> & { password?: string }) {
    setMessage(null);
    try {
      const updated = await api.updateUser(user.id, patch);
      setUsers((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
      setMessage(`${updated.display_name} 已更新。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  }

  if (currentUser.role !== "admin") {
    return (
      <section className="panel">
        <PanelTitle icon={Users} title="账户中心" />
        <EmptyState text="当前账户没有用户管理权限。" />
      </section>
    );
  }

  return (
    <section className="grid-page">
      <div className="metric-row">
        <div className="metric"><span>当前账户</span><strong>{currentUser.display_name}</strong></div>
        <div className="metric"><span>权限</span><strong>{currentUser.role === "admin" ? "管理员" : "普通用户"}</strong></div>
        <div className="metric"><span>用户数</span><strong>{users.length}</strong></div>
        <div className="metric"><span>会话</span><strong>HttpOnly Cookie</strong></div>
      </div>
      <section className="panel span-2">
        <div className="panel-heading">
          <PanelTitle icon={Users} title="用户管理" />
          <button className="small-button" onClick={loadUsers} disabled={loading}>刷新</button>
        </div>
        {message && <div className={message.includes("失败") || message.includes("权限") ? "alert" : "auth-note"}>{message}</div>}
        <div className="user-list">
          {users.map((user) => (
            <UserEditor key={user.id} user={user} isSelf={user.id === currentUser.id} onSave={saveUser} />
          ))}
        </div>
      </section>
      <section className="panel">
        <PanelTitle icon={ShieldCheck} title="账户策略" />
        <div className="data-layers">
          <div><strong>注册</strong><span>新用户默认普通权限；初始空库时首个账户为管理员。</span></div>
          <div><strong>登录</strong><span>密码使用 PBKDF2 加盐哈希，服务端只保存会话 token。</span></div>
          <div><strong>管理</strong><span>管理员可调整角色、状态和重置密码。</span></div>
        </div>
      </section>
    </section>
  );
}

function UserEditor({
  user,
  isSelf,
  onSave
}: {
  user: AppUser;
  isSelf: boolean;
  onSave: (user: AppUser, patch: Partial<AppUser> & { password?: string }) => void;
}) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [role, setRole] = useState(user.role);
  const [status, setStatus] = useState(user.status);
  const [password, setPassword] = useState("");

  useEffect(() => {
    setDisplayName(user.display_name);
    setRole(user.role);
    setStatus(user.status);
    setPassword("");
  }, [user]);

  return (
    <article className="user-card">
      <div>
        <strong>{user.username}</strong>
        <small>创建 {user.created_at} · 最近登录 {user.last_login_at ?? "-"}</small>
      </div>
      <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} aria-label="显示名称" />
      <select value={role} onChange={(event) => setRole(event.target.value)}>
        <option value="admin">管理员</option>
        <option value="user">普通用户</option>
      </select>
      <select value={status} onChange={(event) => setStatus(event.target.value)} disabled={isSelf}>
        <option value="active">启用</option>
        <option value="disabled">禁用</option>
      </select>
      <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="新密码(可选)" type="password" />
      <button className="small-button" onClick={() => onSave(user, { display_name: displayName, role, status, password })}>保存</button>
    </article>
  );
}
