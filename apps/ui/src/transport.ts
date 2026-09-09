import type { DocumentSession, ModelInventory, RuntimeInfo, Transport } from "@medical-deid/contract";

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

  models() {
    return this.request<ModelInventory>("/api/models");
  }

  installModel(profileId: string) {
    return this.request<ModelInventory>(`/api/models/${profileId}/install`, { method: "POST" });
  }

  selectModel(profileId: string) {
    return this.request<ModelInventory>(`/api/models/${profileId}/select`, { method: "POST" });
  }

  async uploadDocument(document?: File) {
    if (!document) throw new Error("Сначала выберите документ.");
    const form = new FormData();
    form.append("document", document);
    const response = await fetch("/api/documents", { method: "POST", body: form });
    if (!response.ok) throw new Error((await response.json()).detail ?? `HTTP ${response.status}`);
    return response.json() as Promise<DocumentSession>;
  }

  document(sessionId: string) {
    return this.request<DocumentSession>(`/api/documents/${sessionId}`);
  }

  resultUrl(sessionId: string) {
    return `/api/documents/${sessionId}/result`;
  }

  async saveResult(sessionId: string) {
    window.location.assign(this.resultUrl(sessionId));
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
    return this.invoke<RuntimeInfo>("initialize");
  }

  models() {
    return this.invoke<ModelInventory>("models");
  }

  installModel(profileId: string) {
    return this.invoke<ModelInventory>("install_model", { profile_id: profileId });
  }

  selectModel(profileId: string) {
    return this.invoke<ModelInventory>("select_model", { profile_id: profileId });
  }

  async uploadDocument() {
    const sourcePath = await window.__TAURI__?.core.invoke<string | null>("pick_document");
    if (!sourcePath) return null;
    return this.invoke<DocumentSession>("create_document_path", {
      source_path: sourcePath,
    });
  }

  document(sessionId: string) {
    return this.invoke<DocumentSession>("document", { session_id: sessionId });
  }

  resultUrl(_: string) {
    return null;
  }

  async saveResult(sessionId: string) {
    const destinationPath = await window.__TAURI__?.core.invoke<string | null>("pick_result_destination");
    if (!destinationPath) return;
    await this.invoke("save_result", { session_id: sessionId, destination_path: destinationPath });
  }
}

export function selectTransport(): Transport {
  return window.__TAURI__ ? new DesktopTransport() : new WebTransport();
}

export function isDesktopTransport() {
  return window.__TAURI__ !== undefined;
}
