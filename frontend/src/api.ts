import axios from "axios";

// Same-origin by default: the FastAPI backend also serves the built SPA, so the
// frontend's own host IS the API endpoint. In dev, Vite proxies /api and /ws to
// the backend. No VITE_BACKEND_URL needed (kept as an optional override).
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";
const http = axios.create({
  baseURL: BACKEND_URL ? `${BACKEND_URL.replace(/\/$/, "")}/api` : "/api",
});

// ---- token storage helpers ----
const ADMIN_TOKEN = "humanllm_admin_token";

export const tokenStore = {
  getAdmin: () => localStorage.getItem(ADMIN_TOKEN),
  setAdmin: (t: string) => localStorage.setItem(ADMIN_TOKEN, t),
  clearAdmin: () => localStorage.removeItem(ADMIN_TOKEN),
  // Convenience alias used across the single-page admin app (admin IS the worker).
  getWorker: () => localStorage.getItem(ADMIN_TOKEN),
  setWorker: (t: string) => localStorage.setItem(ADMIN_TOKEN, t),
  clearWorker: () => localStorage.removeItem(ADMIN_TOKEN),
};

function auth(token: string | null) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ----------------------------- Auth -----------------------------
export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: string;
  worker_id?: number;
  username?: string;
}

export async function adminLogin(body: { username: string; password: string }) {
  const r = await http.post<TokenResponse>("/auth/admin/login", body);
  return r.data;
}

// ----------------------------- Admin -----------------------------
export interface AdminStats {
  users: number;
  workers: number;
  workers_online: number;
  models: number;
  tasks_total: number;
  tasks_completed: number;
  tasks_pending: number;
  revenue_cents: number;
  worker_payouts_cents: number;
  platform_commission_cents: number;
}

export async function getAdminStats(token: string) {
  const r = await http.get<AdminStats>("/admin/stats", { headers: auth(token) });
  return r.data;
}

export interface CallsTrendPoint {
  date: string;
  count: number;
}
export async function getAdminCallsTrend(token: string, days = 14) {
  const r = await http.get<CallsTrendPoint[]>("/admin/calls-trend", {
    headers: auth(token),
    params: { days },
  });
  return r.data;
}

export interface WorkerPublic {
  id: number;
  username: string;
  display_name: string;
  status: string;
  skills: string[];
  earnings_cents: number;
  current_task_id: string | null;
  served_models: string[];
}

export async function getAdminWorkers(token: string) {
  const r = await http.get<WorkerPublic[]>("/admin/workers", { headers: auth(token) });
  return r.data;
}

export interface ModelPublic {
  id: number;
  name: string;
  display_name: string;
  description: string;
  price_per_request_cents: number;
  price_per_1k_chars_cents: number;
  price_per_minute_cents: number;
  concurrency: number;
  timeout_seconds: number;
  is_active: boolean;
  created_at: string;
  worker_usernames: string[];
}

export async function getAdminModels(token: string) {
  const r = await http.get<ModelPublic[]>("/admin/models", { headers: auth(token) });
  return r.data;
}

export async function createAdminModel(
  token: string,
  body: {
    name: string;
    display_name?: string;
    description?: string;
    price_per_request_cents?: number;
    price_per_1k_chars_cents?: number;
    price_per_minute_cents?: number;
    concurrency?: number;
    timeout_seconds?: number;
    worker_usernames?: string[];
  }
) {
  const r = await http.post<ModelPublic>("/admin/models", body, { headers: auth(token) });
  return r.data;
}

export interface ApiKeyRow {
  id: number;
  name: string | null;
  key_prefix: string;
  full_key: string | null;
  user_id: number;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string | null;
}

export async function getAdminApiKeys(token: string) {
  const r = await http.get<ApiKeyRow[]>("/admin/apikeys", { headers: auth(token) });
  return r.data;
}

export interface TaskPublic {
  id: string;
  model: string;
  user_id: number | null;
  api_key_id: number | null;
  status: string;
  stream: boolean;
  reply_text: string;
  usage: Record<string, unknown> | null;
  error: string | null;
  finish_reason: string | null;
  created_at: string;
  assigned_at: string | null;
  completed_at: string | null;
  assigned_worker_id: number | null;
}

export async function getAdminTasks(token: string, limit = 50) {
  const r = await http.get<TaskPublic[]>("/admin/tasks", {
    headers: auth(token),
    params: { limit },
  });
  return r.data;
}

export interface UsageRow {
  id: number;
  kind: string;
  task_id: string | null;
  user_id: number | null;
  worker_id: number | null;
  amount_cents: number;
  note: string | null;
  created_at: string | null;
}


export async function cancelAdminTask(token: string, taskId: string) {
  const r = await http.post<TaskPublic>(`/admin/tasks/${taskId}/cancel`, {}, {
    headers: auth(token),
  });
  return r.data;
}

export async function getAdminUsage(token: string) {
  const r = await http.get<UsageRow[]>("/admin/usage", { headers: auth(token) });
  return r.data;
}

export interface LogRow {
  id: number;
  kind: string;
  actor: string;
  task_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string | null;
}

export async function getAdminLogs(token: string, limit = 100) {
  const r = await http.get<LogRow[]>("/admin/logs", {
    headers: auth(token),
    params: { limit },
  });
  return r.data;
}

export { http };


// ----------------------------- Worker (接单工作台) -----------------------------
export interface PendingTask {
  id: string;
  model: string;
  status: string;
  preview: string;
}

export interface WorkerTaskList {
  pending: PendingTask[];
  active: { id: string; model: string; status: string } | null;
}

export async function getWorkerTasks(token: string) {
  const r = await http.get<WorkerTaskList>("/worker/tasks", { headers: auth(token) });
  return r.data;
}


// ----------------------------- Users (用户管理，仅超级管理员) -----------------------------
export type UserRole = "super_admin" | "staff";

export interface UserPublic {
  id: number;
  username: string;
  email: string | null;
  role: UserRole;
  permissions: string[] | null;
  is_active: boolean;
  balance_cents: number;
  created_at: string;
  worker_status: string | null;
  worker_id: number | null;
  is_initial_admin?: boolean;
}

export interface UserCreate {
  username: string;
  password: string;
  email?: string | null;
  role?: UserRole;
  permissions?: string[];
}

export interface UserUpdate {
  role?: UserRole | null;
  permissions?: string[] | null;
  is_active?: boolean | null;
  password?: string | null;
  email?: string | null;
}

export interface PermGroup {
  group: string;
  label: string;
  items: { key: string; label: string }[];
}

// 权限分组：每个业务模块拆成「查看」与「管理（含增删改）」两个粒度。
export const ALL_PERMISSION_GROUPS: PermGroup[] = [
  { group: "overview", label: "概览", items: [{ key: "overview_view", label: "查看概览" }] },
  { group: "workbench", label: "接单工作台", items: [{ key: "workbench", label: "接单工作台" }] },
  {
    group: "models",
    label: "模型",
    items: [
      { key: "models_view", label: "查看模型" },
      { key: "models_manage", label: "管理模型（创建/编辑/删除）" },
    ],
  },
  {
    group: "apikeys",
    label: "API 密钥",
    items: [
      { key: "apikeys_view", label: "查看密钥" },
      { key: "apikeys_manage", label: "管理密钥（创建/删除）" },
    ],
  },
  {
    group: "tasks",
    label: "任务",
    items: [
      { key: "tasks_view", label: "查看任务" },
      { key: "tasks_manage", label: "管理任务（取消等）" },
    ],
  },
  { group: "usage", label: "用量", items: [{ key: "usage_view", label: "查看用量" }] },
  { group: "logs", label: "日志", items: [{ key: "logs_view", label: "查看日志" }] },
];

// 扁平化，便于后端权限数组比对。
export const ALL_PERMISSIONS: string[] = ALL_PERMISSION_GROUPS.flatMap((g) =>
  g.items.map((i) => i.key)
);

export function permLabel(key: string): string {
  for (const g of ALL_PERMISSION_GROUPS) {
    const it = g.items.find((i) => i.key === key);
    if (it) return it.label;
  }
  return key;
}

export async function getAdminUsers(token: string) {
  const r = await http.get<UserPublic[]>("/admin/users", { headers: auth(token) });
  return r.data;
}

export async function createAdminUser(token: string, body: UserCreate) {
  const r = await http.post<UserPublic>("/admin/users", body, { headers: auth(token) });
  return r.data;
}

export async function updateAdminUser(token: string, userId: number, body: UserUpdate) {
  const r = await http.patch<UserPublic>(`/admin/users/${userId}`, body, { headers: auth(token) });
  return r.data;
}

// ----------------------------- API Keys (创建) -----------------------------
export interface ApiKeyCreated {
  id: number;
  name: string;
  key: string;
  key_prefix: string;
}

export async function createAdminApiKey(token: string, name: string) {
  const r = await http.post<ApiKeyCreated>("/admin/apikeys", { name }, { headers: auth(token) });
  return r.data;
}
export async function deleteAdminModel(token: string, name: string) {
  const r = await http.delete(`/admin/models/${encodeURIComponent(name)}`, { headers: auth(token) });
  return r.data;
}

// ----------------------------- 删除：用户 / API 密钥 -----------------------------
export async function deleteAdminUser(token: string, userId: number) {
  const r = await http.delete(`/admin/users/${userId}`, { headers: auth(token) });
  return r.data;
}

export async function deleteAdminApiKey(token: string, keyId: number) {
  const r = await http.delete(`/admin/apikeys/${keyId}`, { headers: auth(token) });
  return r.data;
}

export interface UserEarningItem {
  id: number;
  task_id: string | null;
  amount_cents: number;
  note: string | null;
  created_at: string | null;
}
export interface UserEarnings {
  user_id: number;
  username: string;
  total_cents: number;
  count: number;
  items: UserEarningItem[];
}

export async function getAdminUserEarnings(token: string, userId: number) {
  const r = await http.get<UserEarnings>(`/admin/users/${userId}/earnings`, { headers: auth(token) });
  return r.data;
}
