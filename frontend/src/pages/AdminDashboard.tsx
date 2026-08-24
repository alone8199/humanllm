import { useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  tokenStore,
  getAdminStats,
  getAdminModels,
  getAdminApiKeys,
  getAdminTasks,
  cancelAdminTask,
  getAdminUsage,
  getAdminLogs,
  getWorkerTasks,
  PendingTask,
  WorkerTaskList,
  AdminStats,
  ModelPublic,
  ApiKeyRow,
  deleteAdminModel,
  deleteAdminUser,
  deleteAdminApiKey,
  getAdminUserEarnings,
  ALL_PERMISSION_GROUPS,
  permLabel,
  TaskPublic,
  UsageRow,
  LogRow,
  UserEarnings,
  getAdminUsers,
  createAdminUser,
  updateAdminUser,
  createAdminApiKey,
  UserPublic,
  UserCreate,
  UserUpdate,
  UserRole,
  getAdminCallsTrend,
  CallsTrendPoint,
} from "../api";
import {
  WorkerSocket,
  AssignedTask,
  ChatMessage,
  ChatContentPart,
} from "../ws";
import {
  LogoIcon,
  OverviewIcon,
  WorkbenchIcon,
  UsersIcon,
  ModelsIcon,
  KeyIcon,
  TasksIcon,
  UsageIcon,
  LogsIcon,
  LogoutIcon,
} from "../Icon";
import ThemeToggle from "../ThemeToggle";

type Tab = "overview" | "workbench" | "users" | "models" | "apikeys" | "tasks" | "usage" | "logs";

export default function AdminDashboard() {
  const token = tokenStore.getAdmin() as string;
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<AdminStats | null>(null);

  useEffect(() => {
    getAdminStats(token)
      .then(setStats)
      .catch(() => {
        tokenStore.clearAdmin();
        window.location.assign("/login");
      });
  }, [token]);

  const navItems: [Tab, string, JSX.Element][] = [
    ["overview", "概览", <OverviewIcon />],
    ["workbench", "接单", <WorkbenchIcon />],
    ["users", "用户", <UsersIcon />],
    ["models", "模型", <ModelsIcon />],
    ["apikeys", "API 密钥", <KeyIcon />],
    ["tasks", "任务", <TasksIcon />],
    ["usage", "用量", <UsageIcon />],
    ["logs", "日志", <LogsIcon />],
  ];

  function logout() {
    tokenStore.clearAdmin();
    window.location.assign("/login");
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="side-brand">
          <span className="side-logo">
            <LogoIcon size={24} />
          </span>
          <div className="side-brand-text">
            <span className="side-title">请调用我</span>
            <span className="side-sub">管理后台 · 你就是模型</span>
          </div>
        </div>

        <nav className="side-nav">
          {navItems.map(([k, label, icon]) => (
            <button
              key={k}
              className={tab === k ? "active" : ""}
              onClick={() => setTab(k)}
            >
              <span className="nav-ico">{icon}</span>
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="side-foot">
          <ThemeToggle />
          <button className="side-logout" onClick={logout}>
            <span className="nav-ico"><LogoutIcon /></span>
            <span>登出</span>
          </button>
        </div>
      </aside>

      <div className="main">
        <main className="content">
          {tab === "overview" && <Overview stats={stats} />}
          {tab === "workbench" && <Workbench token={token} />}
          {tab === "users" && <Users token={token} />}
          {tab === "models" && <Models token={token} />}
          {tab === "apikeys" && <ApiKeys token={token} />}
          {tab === "tasks" && <Tasks token={token} />}
          {tab === "usage" && <Usage token={token} />}
          {tab === "logs" && <Logs token={token} />}
        </main>
      </div>
    </div>
  );
}

// 读取 CSS 主题变量（Recharts 的 SVG 属性不支持 var()，需读具体值）
function useThemeColors() {
  const [c, setC] = useState(() => readColors());
  useEffect(() => {
    setC(readColors());
    const mo = new MutationObserver(() => setC(readColors()));
    mo.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => mo.disconnect();
  }, []);
  return c;
}
function readColors() {
  const s = getComputedStyle(document.documentElement);
  const g = (n: string) => s.getPropertyValue(n).trim() || "#0a84ff";
  return {
    accent: g("--accent"),
    border: g("--border"),
    muted: g("--muted"),
    card: g("--card"),
    text: g("--text"),
  };
}

// 调用趋势图（Recharts）：极简折线 + 面积渐变，hover 显示具体数值
function CallsChart({ data }: { data: CallsTrendPoint[] }) {
  const col = useThemeColors();
  if (!data || data.length === 0) {
    return <p className="muted">暂无调用数据。</p>;
  }
  return (
    <div className="calls-chart">
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="callsFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={col.accent} stopOpacity={0.28} />
              <stop offset="100%" stopColor={col.accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={col.border} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: col.muted, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: col.border }}
            minTickGap={20}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: col.muted, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={36}
          />
          <Tooltip
            cursor={{ stroke: col.accent, strokeOpacity: 0.3 }}
            contentStyle={{
              background: col.card,
              border: `1px solid ${col.border}`,
              borderRadius: 10,
              color: col.text,
              fontSize: 13,
            }}
            labelStyle={{ color: col.muted }}
            formatter={(v: any) => [`${v} 次`, "调用"]}
          />
          <Area
            type="monotone"
            dataKey="count"
            stroke={col.accent}
            strokeWidth={2}
            fill="url(#callsFill)"
            dot={{ r: 2.5, fill: col.accent, strokeWidth: 0 }}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Overview({ stats }: { stats: AdminStats | null }) {
  const [trend, setTrend] = useState<CallsTrendPoint[]>([]);
  const token = tokenStore.getAdmin() as string;
  useEffect(() => {
    getAdminCallsTrend(token, 14).then(setTrend).catch(() => {});
  }, [token]);
  if (!stats) return <p className="muted">加载中…</p>;

  const todayCalls = trend.length ? trend[trend.length - 1].count : 0;
  const cards = [
    { label: "模型", value: stats.models, ico: <ModelsIcon />, tone: "" },
    { label: "任务总数", value: stats.tasks_total, sub: `${stats.tasks_pending} 进行中`, ico: <TasksIcon />, tone: "" },
    { label: "已完成", value: stats.tasks_completed, ico: <TasksIcon />, tone: "green" },
    { label: "今日调用", value: todayCalls, ico: <UsageIcon />, tone: "green" },
    { label: "进行中任务", value: stats.tasks_pending, ico: <WorkbenchIcon />, tone: "amber" },
  ];
  return (
    <div>
      <div className="page-head">
        <h1>概览</h1>
        <p className="page-desc">平台核心指标与最近 14 天的调用趋势。</p>
      </div>

      <div className="stat-grid">
        {cards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className="stat-top">
              <span className={`stat-ico ${c.tone}`}>{c.ico}</span>
              {c.sub && <span className="badge status-muted">{c.sub}</span>}
            </div>
            <div>
              <div className="stat-value">{c.value}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="chart-card">
        <div className="chart-head">
          <h3>最近调用趋势</h3>
          <span className="muted">最近 14 天</span>
        </div>
        <CallsChart data={trend} />
      </div>
    </div>
  );
}

function Models({ token }: { token: string }) {
  const [models, setModels] = useState<ModelPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    name: "",
    display_name: "",
    description: "",
    price_per_request_cents: 0,
    price_per_1k_chars_cents: 0,
    price_per_minute_cents: 0,
    concurrency: 1,
    timeout_seconds: 600,
    worker_usernames: "",
  });
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    getAdminModels(token).then(setModels).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [token]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await fetch("/api/admin/models", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          ...form,
          worker_usernames: form.worker_usernames
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      }).then((r) => {
        if (!r.ok) throw new Error("create failed");
        return r.json();
      });
      setMsg("模型创建成功。");
      setForm({
        name: "",
        display_name: "",
        description: "",
        price_per_request_cents: 0,
        price_per_1k_chars_cents: 0,
        price_per_minute_cents: 0,
        concurrency: 1,
        timeout_seconds: 600,
        worker_usernames: "",
      });
      load();
    } catch {
      setMsg("模型创建失败。");
    }
  }

  const [busyDel, setBusyDel] = useState<string | null>(null);
  async function delModel(name: string) {
    if (!confirm(`确定删除模型「${name}」？此操作不可撤销。`)) return;
    setBusyDel(name);
    try {
      await deleteAdminModel(token, name);
      setMsg("模型已删除。");
      load();
    } catch (ex: any) {
      setMsg("删除失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    } finally {
      setBusyDel(null);
    }
  }

  return (
    <div className="two-col">
      <div>
        <div className="page-head">
          <h1>模型</h1>
          <p className="page-desc">管理可被调用的模型及其计费、并发与接单账号。</p>
        </div>
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>名称</th>
              <th>显示名</th>
              <th>请求费</th>
              <th>千字费</th>
              <th>分钟费</th>
              <th>并发</th>
              <th>启用</th>
              <th>接单账号</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <td>{m.name}</td>
                <td>{m.display_name}</td>
                <td>{m.price_per_request_cents}</td>
                <td>{m.price_per_1k_chars_cents}</td>
                <td>{m.price_per_minute_cents}</td>
                <td>{m.concurrency}</td>
                <td>{m.is_active ? "✓" : "✗"}</td>
                <td className="wrap">{m.worker_usernames.join("， ") || "—"}</td>
                <td>
                  <div className="tbl-row-actions">
                  <button
                    className="ghost danger"
                    disabled={busyDel === m.name}
                    onClick={() => delModel(m.name)}
                  >
                    {busyDel === m.name ? "删除中…" : "删除"}
                  </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {loading && <p className="muted">加载中…</p>}
      </div>
      <form className="form-col" onSubmit={create}>
        <h3>新建模型</h3>
        <input
          placeholder="名称（如 human-gpt）"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <input
          placeholder="显示名"
          value={form.display_name}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })}
        />
        <textarea
          placeholder="描述"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <input
          type="number"
          placeholder="每次请求价格（分）"
          value={form.price_per_request_cents}
          onChange={(e) =>
            setForm({ ...form, price_per_request_cents: Number(e.target.value) })
          }
        />
        <input
          type="number"
          placeholder="每千字符价格（分）"
          value={form.price_per_1k_chars_cents}
          onChange={(e) =>
            setForm({ ...form, price_per_1k_chars_cents: Number(e.target.value) })
          }
        />
        <input
          type="number"
          placeholder="每分钟价格（分）"
          value={form.price_per_minute_cents}
          onChange={(e) =>
            setForm({ ...form, price_per_minute_cents: Number(e.target.value) })
          }
        />
        <input
          type="number"
          placeholder="并发数"
          value={form.concurrency}
          onChange={(e) => setForm({ ...form, concurrency: Number(e.target.value) })}
        />
        <input
          type="number"
          placeholder="超时时间（秒）"
          value={form.timeout_seconds}
          onChange={(e) =>
            setForm({ ...form, timeout_seconds: Number(e.target.value) })
          }
        />
        <input
          placeholder="接单账号（逗号分隔）"
          value={form.worker_usernames}
          onChange={(e) => setForm({ ...form, worker_usernames: e.target.value })}
        />
        <button className="primary" type="submit">
          创建模型
        </button>
        {msg && <div className="info">{msg}</div>}
      </form>
    </div>
  );
}

function ApiKeys({ token }: { token: string }) {
  const [rows, setRows] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyDel, setBusyDel] = useState<number | null>(null);

  async function delKey(id: number) {
    if (!confirm("确定删除该 API 密钥？删除后不可恢复。")) return;
    setBusyDel(id);
    try {
      await deleteAdminApiKey(token, id);
      load();
    } catch (ex: any) {
      setErr("删除失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    } finally {
      setBusyDel(null);
    }
  }

  const load = () => {
    getAdminApiKeys(token).then(setRows).catch(() => {});
  };
  useEffect(load, [token]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setCreated(null);
    if (!name.trim()) {
      setErr("请填写密钥名称。");
      return;
    }
    setBusy(true);
    try {
      const r = await createAdminApiKey(token, name.trim());
      setCreated(r.key);
      setName("");
      load();
    } catch (ex: any) {
      setErr("创建失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>API 密钥</h1>
        <p className="page-desc">为用户签发调用凭证，密钥仅创建时完整可见一次。</p>
      </div>
      <form className="form-col" style={{ maxWidth: 420, marginBottom: 18 }} onSubmit={create}>
        <h3>创建 API 密钥</h3>
        <input
          placeholder="密钥名称（如 default）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "创建中…" : "创建密钥"}
        </button>
        {created && (
          <div className="info">
            密钥已创建（仅显示一次）：<br />
            <code style={{ wordBreak: "break-all" }}>{created}</code>
          </div>
        )}
        {err && <div className="form-error">{err}</div>}
      </form>

      <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>前缀</th>
            <th>用户</th>
            <th>启用</th>
            <th>最后使用</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((k) => (
            <tr key={k.id}>
              <td>{k.id}</td>
              <td>{k.name || "—"}</td>
              <td>{k.key_prefix}</td>
              <td>{k.user_id}</td>
              <td>{k.is_active ? "✓" : "✗"}</td>
              <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "—"}</td>
              <td>{k.created_at ? new Date(k.created_at).toLocaleString() : "—"}</td>
              <td>
                <div className="tbl-row-actions">
                <button
                  className="ghost danger"
                  disabled={busyDel === k.id}
                  onClick={() => delKey(k.id)}
                >
                  {busyDel === k.id ? "删除中…" : "删除"}
                </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function Tasks({ token }: { token: string }) {
  const [rows, setRows] = useState<TaskPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const load = () => {
    setLoading(true);
    getAdminTasks(token).then(setRows).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [token]);

  const cancellable = (status: string) =>
    status === "pending" || status === "assigned" || status === "waiting_tool";

  const do取消 = async (id: string) => {
    if (!confirm("确定取消该订单？")) return;
    setBusy(id);
    try {
      await cancelAdminTask(token, id);
      load();
    } catch (e: any) {
      alert("取消失败：" + (e?.response?.data?.detail || e?.message || "未知错误"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>任务</h1>
        <p className="page-desc">查看所有调用任务及其生命周期状态，可取消进行中的任务。</p>
      </div>
      <div className="toolbar">
        <div className="spacer" />
        <button className="ghost" onClick={load} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>
      {rows.length === 0 && !loading ? (
        <div className="empty"><div className="empty-ico"><TasksIcon /></div>暂无任务记录。</div>
      ) : (
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>ID</th>
              <th>模型</th>
              <th>状态</th>
              <th>流式</th>
              <th>接单账号</th>
              <th>创建时间</th>
              <th>完成时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td className="mono">{t.id.slice(0, 8)}</td>
                <td>{t.model}</td>
                <td>
                  <span className={`badge status-${t.status}`}>{t.status === "pending" ? "待分配" : t.status === "assigned" ? "已分配" : t.status === "streaming" ? "流式中" : t.status === "completed" ? "已完成" : t.status === "cancelled" ? "已取消" : t.status === "timeout" ? "超时" : t.status === "waiting_tool" ? "等待工具" : t.status}</span>
                </td>
                <td>{t.stream ? "是" : "否"}</td>
                <td>{t.assigned_worker_id ?? "—"}</td>
                <td>{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</td>
                <td>
                  {t.completed_at ? new Date(t.completed_at).toLocaleString() : "—"}
                </td>
                <td>
                  <div className="tbl-row-actions">
                  {cancellable(t.status) && (
                    <button
                      className="ghost danger"
                      disabled={busy === t.id}
                      onClick={() => do取消(t.id)}
                    >
                      {busy === t.id ? "取消中…" : "取消订单"}
                    </button>
                  )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}

function Usage({ token }: { token: string }) {
  const [rows, setRows] = useState<UsageRow[]>([]);
  const [loading, setLoading] = useState(false);
  const load = () => {
    setLoading(true);
    getAdminUsage(token).then(setRows).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [token]);
  return (
    <div>
      <div className="page-head">
        <h1>用量</h1>
        <p className="page-desc">所有计费流水，包括调用扣费与接单账号收益。</p>
      </div>
      <div className="toolbar">
        <div className="spacer" />
        <button className="ghost" onClick={load} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>
      {rows.length === 0 && !loading ? (
        <div className="empty">暂无用量记录。</div>
      ) : (
      <div className="tbl-wrap">
      <table className="tbl">
      <thead>
        <tr>
          <th>ID</th>
          <th>类型</th>
          <th>任务</th>
          <th>用户</th>
          <th>接单账号</th>
          <th>金额</th>
          <th>备注</th>
          <th>时间</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((u) => (
          <tr key={u.id}>
            <td>{u.id}</td>
            <td>{u.kind}</td>
            <td className="mono">{u.task_id ? u.task_id.slice(0, 8) : "—"}</td>
            <td>{u.user_id ?? "—"}</td>
            <td>{u.worker_id ?? "—"}</td>
            <td>{u.amount_cents}¢</td>
            <td>{u.note || "—"}</td>
            <td>{u.created_at ? new Date(u.created_at).toLocaleString() : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
      </div>
      )}
    </div>
  );
}

function Logs({ token }: { token: string }) {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [loading, setLoading] = useState(false);
  const load = () => {
    setLoading(true);
    getAdminLogs(token).then(setRows).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [token]);
  return (
    <div>
      <div className="page-head">
        <h1>日志</h1>
        <p className="page-desc">管理员操作与系统事件的审计记录。</p>
      </div>
      <div className="toolbar">
        <div className="spacer" />
        <button className="ghost" onClick={load} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>
      {rows.length === 0 && !loading ? (
        <div className="empty">暂无日志。</div>
      ) : (
      <div className="tbl-wrap">
      <table className="tbl">
      <thead>
        <tr>
          <th>ID</th>
          <th>类型</th>
          <th>操作者</th>
          <th>任务</th>
          <th>详情</th>
          <th>时间</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((l) => (
          <tr key={l.id}>
            <td>{l.id}</td>
            <td>{l.kind}</td>
            <td>{l.actor}</td>
            <td className="mono">{l.task_id ? l.task_id.slice(0, 8) : "—"}</td>
            <td className="mono wrap">{l.detail ? JSON.stringify(l.detail) : "—"}</td>
            <td>{l.created_at ? new Date(l.created_at).toLocaleString() : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
      </div>
      )}
    </div>
  );
}

// ----------------------------- Workbench (接单) -----------------------------
// The admin IS the only human worker. Connect over the same WebSocket channel
// a worker would use. Pending tasks show up in the queue (right column) and can
// be grabbed manually; auto-assigned tasks arrive as `task_assigned` (left column).
// Defensive rendering: any missing field must never throw, or React unmounts the
// whole tree and the page goes blank ("接单页面消失").

function safeContent(content: string | ChatContentPart[] | null | undefined): ChatContentPart[] {
  // Normalize a message body into a list of parts we can render safely.
  if (content == null) return [];
  if (typeof content === "string") return [{ type: "text", text: content }];
  if (!Array.isArray(content)) return [];
  return content.filter(
    (p): p is ChatContentPart =>
      p != null && typeof p === "object" && typeof (p as any).type === "string"
  );
}

function renderContent(content: string | ChatContentPart[] | null | undefined): JSX.Element {
  const parts = safeContent(content);
  if (parts.length === 0) {
    return <span className="msg-text muted">（空消息）</span>;
  }
  return (
    <>
      {parts.map((part, i) => {
        if (part.type === "text") {
          return (
            <span className="msg-text" key={i}>
              {part.text}
            </span>
          );
        }
        if (part.type === "image_url") {
          const url = part.image_url?.url ?? "#";
          return (
            <a key={i} href={url} target="_blank" rel="noreferrer">
              <img className="msg-img" src={url} alt="attachment" />
            </a>
          );
        }
        if (part.type === "file_url") {
          const url = part.file_url?.url ?? "#";
          return (
            <a
              key={i}
              className="msg-file"
              href={url}
              target="_blank"
              rel="noreferrer"
            >
              📎 Open attached file
            </a>
          );
        }
        return null;
      })}
    </>
  );
}

function Workbench({ token }: { token: string }) {
  const [connected, setConnected] = useState(false);
  const [task, setTask] = useState<AssignedTask | null>(null);
  const [reply, setReply] = useState("");
  const [streamed, setStreamed] = useState("");
  const [done, setDone] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [queue, setQueue] = useState<PendingTask[]>([]);
  const [grabbing, setGrabbing] = useState<string | null>(null);

  const socketRef = useRef<WorkerSocket | null>(null);
  const replyRef = useRef("");
  replyRef.current = reply;

  // REST: refresh the grab-able queue.
  const loadQueue = () => {
    getWorkerTasks(token)
      .then((data: WorkerTaskList) => {
        const pending = Array.isArray(data?.pending) ? data.pending : [];
        setQueue(pending);
        // If a task is already active on the server, surface it (covers reconnect).
        if (data?.active && !task) {
          // We don't have full messages here; the WS `task_assigned` will fill it.
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadQueue();
    const sock = new WorkerSocket(
      token,
      (msg) => {
        if (msg.type === "task_assigned") {
          const t = (msg as any).task;
          if (t && t.id) {
            setTask(t as AssignedTask);
            setStreamed("");
            setDone(false);
            setReply("");
            setInfo(null);
            setQueue((q) => q.filter((x) => x.id !== t.id));
          }
        } else if (msg.type === "new_task") {
          // A new task entered the grab pool — refresh the queue.
          loadQueue();
        } else if (msg.type === "cancelled") {
          // This worker's task was cancelled server-side.
          setTask((cur) => {
            const cancelledId = (msg as any).task_id;
            if (!cancelledId || !cur || cur.id === cancelledId) {
              setInfo("该任务已被取消。");
              setStreamed("");
              setReply("");
              setDone(false);
              return null;
            }
            return cur;
          });
          loadQueue();
        } else if (msg.type === "pong") {
          /* heartbeat */
        } else if (msg.type === "error") {
          setInfo(`服务器：${msg.message}`);
          setGrabbing(null);
        }
      },
      (isUp) => setConnected(isUp)
    );
    sock.connect();
    socketRef.current = sock;
    const timer = setInterval(loadQueue, 8000); // keep queue fresh
    return () => {
      clearInterval(timer);
      sock.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function grab(id: string) {
    if (!id || grabbing) return;
    setGrabbing(id);
    socketRef.current?.grab(id);
    // Optimistically drop from queue; WS `task_assigned` will reveal the task.
    setQueue((q) => q.filter((x) => x.id !== id));
    // Safety net: if no task_assigned arrives, re-enable after a moment.
    setTimeout(() => setGrabbing(null), 4000);
  }

  function sendChunk() {
    if (!task) return;
    const text = replyRef.current;
    if (!text) return;
    socketRef.current?.chunk(task.id, text);
    setStreamed((s) => s + text);
    setReply("");
  }

  function finish() {
    if (!task) return;
    const finishedId = task.id;
    const full = streamed + replyRef.current;
    socketRef.current?.done(task.id, full);
    setStreamed(full);
    setReply("");
    setDone(true);
    setInfo("已发送给调用方，即将关闭…");
    // 回复完成后约 1 秒，当前任务卡片自动消失（流式输出期间不会触发）。
    // 仅当该任务仍是当前任务时才清除，避免误清掉延迟期间新接到的任务。
    window.setTimeout(() => {
      setTask((cur) => (cur && cur.id === finishedId ? null : cur));
      setStreamed("");
      setReply("");
      setDone(false);
      setInfo(null);
      loadQueue();
    }, 1000);
  }

  function cancel() {
    if (!task) return;
    socketRef.current?.cancel(task.id);
    setInfo("任务已取消。");
    setTask(null);
    setStreamed("");
    setReply("");
    setDone(false);
    loadQueue();
  }

  const attachments = task?.attachments ?? [];

  return (
    <div className="wb">
      <div className="page-head">
        <h1>接单工作台</h1>
        <p className="page-desc">你就是模型本身：从右侧队列接单，或等待系统自动分配。</p>
      </div>
      <div className="wb-status">
        <span className={`dot ${connected ? "on" : "off"}`} />
        {connected ? "已连接 — 你正在线" : "离线"}
      </div>

      <div className="wb-body">
        {/* ---- Left: current task ---- */}
        <section className="wb-task">
          <h2>当前任务</h2>
          {!task && <p className="muted">暂无进行中的任务。可以从右侧队列接单，也可以等待自动分配。</p>}
          {task && (
            <div className="task-card">
              <div className="task-head">
                <span className="badge">{task.model}</span>
                <span className="task-id">{task.id}</span>
                <span className="badge stream">
                  {task.stream ? "流式" : "缓冲"}
                </span>
                {done && <span className="badge done">已完成</span>}
              </div>

              <div className="convo">
                {(task.messages ?? []).map((m: ChatMessage, i) => (
                  <div key={i} className={`bubble ${m?.role ?? "unknown"}`}>
                    <div className="bubble-role">{m?.role === "system" ? "系统" : m?.role === "user" ? "用户" : m?.role === "assistant" ? "助手" : (m?.role ?? "?")}</div>
                    {renderContent(m?.content)}
                  </div>
                ))}
              </div>

              {attachments.length > 0 && (
                <div className="attachments">
                  <strong>附件</strong>
                  {attachments.map((a) => (
                    <div key={a.id} className="attach">
                      {a.content_type && a.content_type.startsWith("image/") ? (
                        <a href={a.url} target="_blank" rel="noreferrer">
                          <img src={a.url} alt={a.filename} className="attach-img" />
                        </a>
                      ) : (
                        <a href={a.url} target="_blank" rel="noreferrer" className="attach-file">
                          📎 {a.filename}
                        </a>
                      )}
                      <span className="attach-meta">{a.content_type}</span>
                    </div>
                  ))}
                </div>
              )}

              {streamed && (
                <div className="reply-stream">
                  <strong>已发送内容（实时）：</strong>
                  <pre>{streamed}</pre>
                </div>
              )}

              <textarea
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="输入人工回复…"
                rows={5}
                disabled={done}
              />

              <div className="task-actions">
                <button className="primary" onClick={sendChunk} disabled={done || !reply}>
                  发送片段
                </button>
                <button className="primary" onClick={finish} disabled={done}>
                  完成
                </button>
                <button className="ghost danger" onClick={cancel} disabled={done}>
                  取消
                </button>
              </div>
            </div>
          )}
          {info && <div className="info">{info}</div>}
        </section>

        {/* ---- Right: grab queue ---- */}
        <aside className="wb-queue">
          <h2>接单队列 ({queue.length})</h2>
          {queue.length === 0 && <p className="muted">暂无待接任务。</p>}
          {queue.map((item) => (
            <div key={item.id} className="queue-item">
              <div className="queue-head">
                <span className="badge">{item.model}</span>
                <span className="task-id">{item.id}</span>
              </div>
              <div className="queue-preview">{item.preview || "（无预览）"}</div>
              <button
                className="ghost"
                onClick={() => grab(item.id)}
                disabled={grabbing === item.id}
              >
                {grabbing === item.id ? "接单中…" : "接单"}
              </button>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}

// ----------------------------- 用户管理（超级管理员） -----------------------------
function Users({ token }: { token: string }) {
  const [rows, setRows] = useState<UserPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<UserPublic | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 创建表单
  const [cUsername, setCUsername] = useState("");
  const [cPassword, setCPassword] = useState("");
  const [cEmail, setCEmail] = useState("");
  const [cRole, setCRole] = useState<UserRole>("staff");
  const [cPerms, setCPerms] = useState<string[]>(["overview_view", "workbench", "apikeys_view"]);

  // 编辑表单
  const [eRole, setERole] = useState<UserRole>("staff");
  const [ePerms, setEPerms] = useState<string[]>([]);
  const [eActive, setEActive] = useState(true);
  const [ePassword, setEPassword] = useState("");

  const load = () => {
    setLoading(true);
    getAdminUsers(token).then(setRows).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [token]);

  const [busyDel, setBusyDel] = useState<number | null>(null);
  async function delUser(u: UserPublic) {
    if (!confirm(`确定删除用户「${u.username}」？该用户的 API 密钥与接单账号会一并删除，操作不可撤销。`)) return;
    setBusyDel(u.id);
    setErr(null);
    try {
      await deleteAdminUser(token, u.id);
      setMsg("用户已删除。");
      if (viewing === u.id) setViewing(null);
      load();
    } catch (ex: any) {
      setErr("删除失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    } finally {
      setBusyDel(null);
    }
  }

  // 选中用户查看其收益明细
  const [viewing, setViewing] = useState<number | null>(null);
  const [earnings, setEarnings] = useState<UserEarnings | null>(null);
  const [earnLoading, setEarnLoading] = useState(false);
  async function viewEarnings(u: UserPublic) {
    setViewing(u.id);
    setEarnLoading(true);
    setEarnings(null);
    try {
      const data = await getAdminUserEarnings(token, u.id);
      setEarnings(data);
    } catch (ex: any) {
      setErr("加载收益失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    } finally {
      setEarnLoading(false);
    }
  }

  function toggle(list: string[], key: string): string[] {
    return list.includes(key) ? list.filter((x) => x !== key) : [...list, key];
  }

  async function doCreate(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!cUsername.trim() || !cPassword) {
      setErr("用户名和密码不能为空。");
      return;
    }
    try {
      const body: UserCreate = {
        username: cUsername.trim(),
        password: cPassword,
        email: cEmail.trim() || null,
        role: cRole,
        permissions: cRole === "staff" ? cPerms : [],
      };
      await createAdminUser(token, body);
      setMsg("用户创建成功。");
      setCUsername(""); setCPassword(""); setCEmail("");
      setCPerms(["overview", "workbench", "apikeys"]);
      setShowCreate(false);
      load();
    } catch (ex: any) {
      setErr("创建失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    }
  }

  function openEdit(u: UserPublic) {
    setEditing(u);
    setERole(u.role);
    setEPerms(u.permissions || []);
    setEActive(u.is_active);
    setEPassword("");
    setErr(null);
    setMsg(null);
  }

  async function doUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setErr(null);
    setMsg(null);
    try {
      const body: UserUpdate = {
        role: eRole,
        permissions: eRole === "staff" ? ePerms : null,
        is_active: eActive,
        password: ePassword || null,
      };
      await updateAdminUser(token, editing.id, body);
      setMsg("用户已更新。");
      setEditing(null);
      load();
    } catch (ex: any) {
      setErr("更新失败：" + (ex?.response?.data?.detail || ex?.message || "未知错误"));
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>用户</h1>
        <p className="page-desc">管理后台账号、角色权限与接单收益，仅超级管理员可见。</p>
      </div>
      <div className="toolbar">
        <button className="primary" style={{ width: "auto" }} onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "收起" : "新建用户"}
        </button>
        <div className="spacer" />
      </div>

      {msg && <div className="info">{msg}</div>}
      {err && <div className="form-error">{err}</div>}

      {showCreate && (
        <form className="form-col" onSubmit={doCreate} style={{ marginBottom: 18 }}>
          <h3>新建用户</h3>
          <input placeholder="用户名" value={cUsername} onChange={(e) => setCUsername(e.target.value)} required />
          <input type="password" placeholder="密码（至少 12 位）" value={cPassword} onChange={(e) => setCPassword(e.target.value)} required />
          <input placeholder="邮箱（可选）" value={cEmail} onChange={(e) => setCEmail(e.target.value)} />
          <label style={{ display: "flex", gap: 8, alignItems: "center", color: "var(--text)" }}>
            角色：
            <select value={cRole} onChange={(e) => setCRole(e.target.value as UserRole)} style={{ flex: 1 }}>
              <option value="staff">普通用户（staff）</option>
              <option value="super_admin">超级管理员</option>
            </select>
          </label>
          {cRole === "staff" && (
            <div>
              <div style={{ color: "var(--muted)", marginBottom: 6 }}>开放权限：</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {ALL_PERMISSION_GROUPS.map((g) => (
                  <div key={g.group}>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{g.label}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                      {g.items.map((p) => (
                        <label key={p.key} style={{ display: "flex", gap: 6, alignItems: "center", color: "var(--text)" }}>
                          <input
                            type="checkbox"
                            checked={cPerms.includes(p.key)}
                            onChange={() => setCPerms((l) => toggle(l, p.key))}
                          />
                          {p.label}
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <button className="primary" type="submit">创建用户</button>
        </form>
      )}

      {editing && (
        <form className="form-col" onSubmit={doUpdate} style={{ marginBottom: 18 }}>
          <h3>编辑用户：{editing.username}</h3>
          <label style={{ display: "flex", gap: 8, alignItems: "center", color: "var(--text)" }}>
            角色：
            <select value={eRole} onChange={(e) => setERole(e.target.value as UserRole)} style={{ flex: 1 }}>
              <option value="staff">普通用户（staff）</option>
              <option value="super_admin">超级管理员</option>
            </select>
          </label>
          {eRole === "staff" && (
            <div>
              <div style={{ color: "var(--muted)", marginBottom: 6 }}>开放权限：</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {ALL_PERMISSION_GROUPS.map((g) => (
                  <div key={g.group}>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{g.label}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                      {g.items.map((p) => (
                        <label key={p.key} style={{ display: "flex", gap: 6, alignItems: "center", color: "var(--text)" }}>
                          <input
                            type="checkbox"
                            checked={ePerms.includes(p.key)}
                            onChange={() => setEPerms((l) => toggle(l, p.key))}
                          />
                          {p.label}
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "center", color: "var(--text)" }}>
            <input type="checkbox" checked={eActive} onChange={(e) => setEActive(e.target.checked)} />
            账号启用
          </label>
          <input type="password" placeholder="重设密码（留空则不修改）" value={ePassword} onChange={(e) => setEPassword(e.target.value)} />
          <div style={{ display: "flex", gap: 10 }}>
            <button className="primary" type="submit">保存</button>
            <button type="button" className="ghost" onClick={() => setEditing(null)}>取消</button>
          </div>
        </form>
      )}

      {loading && <p className="muted">加载中…</p>}
      <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>角色</th>
            <th>权限</th>
            <th>状态</th>
            <th>余额</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id}>
              <td>{u.id}</td>
              <td>{u.username}</td>
              <td>{u.role === "super_admin" ? "超级管理员" : "普通用户"}</td>
              <td className="wrap">{u.role === "super_admin" ? "全部" : (u.permissions || []).map((p) => permLabel(p)).join("、") || "—"}</td>
              <td>{u.is_active ? "启用" : "停用"}</td>
              <td>{u.balance_cents}¢</td>
              <td>
                <div className="tbl-row-actions">
                  <button className="ghost" onClick={() => openEdit(u)}>编辑</button>
                  <button
                    className={viewing === u.id ? "ghost active" : "ghost"}
                    onClick={() => viewEarnings(u)}
                  >
                    收益
                  </button>
                  <button
                    className="ghost danger"
                    disabled={busyDel === u.id || u.is_initial_admin}
                    title={u.is_initial_admin ? "初始管理员账户不可删除" : undefined}
                    onClick={() => delUser(u)}
                  >
                    {busyDel === u.id ? "删除中…" : u.is_initial_admin ? "不可删" : "删除"}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {viewing != null && (
        <div className="earn-panel">
          <div className="earn-head">
            <div>
              <h3 style={{ margin: 0 }}>
                {earnings ? `「${earnings.username}」的收益` : "收益明细"}
              </h3>
              {earnings && (
                <div className="earn-total">
                  累计收益：<b>{earnings.total_cents}¢</b>
                  <span className="muted"> · 共 {earnings.count} 笔</span>
                </div>
              )}
            </div>
            <button className="ghost" onClick={() => setViewing(null)}>收起</button>
          </div>
          {earnLoading && <p className="muted">加载中…</p>}
          {!earnLoading && earnings && earnings.items.length === 0 && (
            <p className="muted">该用户暂无接单收益记录。</p>
          )}
          {!earnLoading && earnings && earnings.items.length > 0 && (
            <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>任务</th>
                  <th>金额</th>
                  <th>备注</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {earnings.items.map((it) => (
                  <tr key={it.id}>
                    <td className="mono">{it.task_id ? it.task_id.slice(0, 8) : "—"}</td>
                    <td>{it.amount_cents}¢</td>
                    <td>{it.note || "—"}</td>
                    <td>{it.created_at ? new Date(it.created_at).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
