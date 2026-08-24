import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminLogin, tokenStore } from "../api";
import { LogoIcon } from "../Icon";

export default function AdminLogin() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, set密码] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await adminLogin({ username, password });
      tokenStore.setAdmin(res.access_token);
      navigate("/");
    } catch (err) {
      const msg =
        (err as any)?.response?.data?.detail ||
        (err as any)?.message ||
        "请求失败";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-logo">
            <LogoIcon size={26} />
          </span>
          <h1>请调用我</h1>
        </div>
        <p className="tagline">管理后台 · 你是唯一的人类接单账号</p>
        <form onSubmit={submit}>
          <label>
            管理员用户名
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => set密码(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "请稍候…" : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
