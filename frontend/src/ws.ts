// Native WebSocket client for the worker workbench channel (/ws/worker?token=..).
// Features: auto-reconnect with backoff, 20s heartbeat, typed message dispatch.

export type WsServerMessage =
  | { type: "task_assigned"; task: AssignedTask }
  | { type: "new_task"; task_id: string; model: string }
  | { type: "cancelled"; task_id?: string }
  | { type: "pong" }
  | { type: "error"; message: string };

export interface Attachment {
  id: string;
  kind: string;
  url: string;
  filename: string;
  content_type: string;
}

export interface AssignedTask {
  id: string;
  model: string;
  messages: ChatMessage[];
  stream: boolean;
  created_at: string | null;
  attachments: Attachment[];
}

export type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } }
  | { type: "file_url"; file_url: { url: string } };

export interface ChatMessage {
  role: string;
  content: string | ChatContentPart[];
}

type MessageHandler = (msg: WsServerMessage) => void;
type StatusHandler = (connected: boolean) => void;

const HEARTBEAT_MS = 20000;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;

export class WorkerSocket {
  private url: string;
  private ws: WebSocket | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private closedByUser = false;
  private onMessage: MessageHandler;
  private onStatus: StatusHandler;

  constructor(token: string, onMessage: MessageHandler, onStatus: StatusHandler) {
    // Same-origin by default (backend also serves the SPA). An explicit
    // VITE_BACKEND_URL overrides this (used only for split dev/prod setups).
    const backend = (import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");
    if (backend) {
      const proto = backend.startsWith("https") ? "wss:" : "ws:";
      const host = backend.replace(/^https?:\/\//, "");
      this.url = `${proto}//${host}/ws/worker?token=${encodeURIComponent(token)}`;
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      this.url = `${proto}//${window.location.host}/ws/worker?token=${encodeURIComponent(token)}`;
    }
    this.onMessage = onMessage;
    this.onStatus = onStatus;
  }

  connect() {
    this.closedByUser = false;
    this.open();
  }

  private open() {
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStatus(true);
      this.startHeartbeat();
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsServerMessage;
        this.onMessage(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      this.stopHeartbeat();
      this.onStatus(false);
      if (!this.closedByUser) this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: "heartbeat" });
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** this.reconnectAttempts,
      RECONNECT_MAX_MS
    );
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  // ---- outbound ----
  private send(obj: Record<string, unknown>) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  grab(taskId: string) {
    this.send({ type: "grab", task_id: taskId });
  }

  chunk(taskId: string, text: string) {
    this.send({ type: "chunk", task_id: taskId, text });
  }

  done(taskId: string, text: string) {
    this.send({ type: "done", task_id: taskId, text });
  }

  cancel(taskId: string) {
    this.send({ type: "cancel", task_id: taskId });
  }

  close() {
    this.closedByUser = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) this.ws.close();
    this.ws = null;
  }
}
