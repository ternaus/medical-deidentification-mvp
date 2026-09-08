import type {
  FeedbackPayload,
  ReviewSession,
  RuntimeInfo,
  Transport,
} from "@medical-deid/contract";

const fixture: ReviewSession = {
  id: "review-fixture",
  status: "completed",
  sourceLabel: "synthetic-review.pdf",
  sourceText:
    "Пациент: Иван Петров\nДата рождения: 14.03.1984\nДата визита: 02.09.2026\nТелефон: +7 900 123-45-67\nРезультат: контрольный осмотр без особенностей.",
  resultText:
    "Пациент: [ИМЯ УДАЛЕНО]\nДата рождения: [ДАТА УДАЛЕНА]\nДата визита: 02.09.2026\nТелефон: [ТЕЛЕФОН УДАЛЁН]\nРезультат: контрольный осмотр без особенностей.",
  changes: [
    { kind: "identifier", source: "Иван Петров", replacement: "[ИМЯ УДАЛЕНО]", reason: "person_name" },
    { kind: "identifier", source: "14.03.1984", replacement: "[ДАТА УДАЛЕНА]", reason: "date_of_birth" },
    { kind: "identifier", source: "+7 900 123-45-67", replacement: "[ТЕЛЕФОН УДАЛЁН]", reason: "phone_number" },
  ],
  warnings: [
    "Интерфейсный fixture: исходный документ не покидает приложение.",
    "Результат не предназначен для клинического или production-использования.",
  ],
  createdAt: new Date().toISOString(),
};

const runtime: RuntimeInfo = {
  mode: "review",
  processingEnabled: false,
  appVersion: "0.1.0",
  coreVersion: "0.1.0",
  ocrVersion: "not-loaded",
  modelVersion: null,
  modelStatus: "not_installed",
  supportedFormats: ["pdf", "jpg", "jpeg", "png"],
};

class ReviewTransport implements Transport {
  async runtime() {
    return runtime;
  }

  async createReviewSession() {
    return { ...fixture, id: crypto.randomUUID(), createdAt: new Date().toISOString() };
  }

  async session(id: string) {
    return { ...fixture, id };
  }

  async feedback(_id: string, _payload: FeedbackPayload) {}

  async removeSession(_id: string) {}
}

class WebTransport implements Transport {
  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) throw new Error((await response.json()).detail ?? `HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }

  runtime() {
    return this.request<RuntimeInfo>("/api/runtime");
  }

  createReviewSession() {
    return this.request<ReviewSession>("/api/review/session", { method: "POST" });
  }

  session(id: string) {
    return this.request<ReviewSession>(`/api/sessions/${id}`);
  }

  async feedback(id: string, payload: FeedbackPayload) {
    await this.request(`/api/sessions/${id}/feedback`, { method: "POST", body: JSON.stringify(payload) });
  }

  async removeSession(id: string) {
    await this.request(`/api/sessions/${id}`, { method: "DELETE" });
  }
}

declare global {
  interface Window {
    __TAURI__?: {
      core: { invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> };
    };
  }
}

class DesktopTransport implements Transport {
  private invoke<T>(operation: string, args: Record<string, unknown> = {}) {
    if (!window.__TAURI__) throw new Error("Tauri bridge is unavailable");
    return window.__TAURI__.core.invoke<T>("worker_request", {
      request: { schema_version: "1.0", operation, request_id: crypto.randomUUID(), ...args },
    });
  }

  runtime() {
    return this.invoke<RuntimeInfo>("initialize", { runtime_mode: "review" });
  }

  createReviewSession() {
    return this.invoke<ReviewSession>("create_review_session");
  }

  session(id: string) {
    return this.invoke<ReviewSession>("get_session", { session_id: id });
  }

  async feedback(id: string, payload: FeedbackPayload) {
    await this.invoke("submit_feedback", { session_id: id, ...payload });
  }

  async removeSession(id: string) {
    await this.invoke("delete_session", { session_id: id });
  }
}

export function selectTransport(): Transport {
  if (window.__TAURI__) return new DesktopTransport();
  if (new URLSearchParams(window.location.search).get("mode") === "web") return new WebTransport();
  return new ReviewTransport();
}
