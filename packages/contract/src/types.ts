export const CONTRACT_VERSION = "1.0" as const;

export type RuntimeMode = "setup" | "local";
export type ModelInstallState = "not_installed" | "downloading" | "ready" | "failed";

export interface RuntimeInfo {
  mode: RuntimeMode;
  processingEnabled: boolean;
  appVersion: string;
  coreVersion: string;
  ocrVersion: string;
  modelVersion: string | null;
  modelStatus: "not_installed" | "ready" | "incompatible";
  supportedFormats: string[];
  accelerator?: { backend: string; label: string; state: ModelInstallState };
}

export interface ModelProfile {
  id: string;
  label: string;
  description: string;
  recommended: boolean;
  state: ModelInstallState;
  downloadedBytes: number;
  totalBytes: number;
  currentAsset: string | null;
  error: string | null;
  sizeBytes: number;
  minMemoryBytes: number;
  minFreeDiskBytes: number;
}

export interface ModelInventory {
  profiles: ModelProfile[];
  selectedProfile: string | null;
  ocrReady: boolean;
  runtime: { backend: string; label: string; state: ModelInstallState };
  preflight: {
    ok: boolean;
    backend: string;
    memoryBytes: number;
    freeDiskBytes: number;
    blockers: string[];
  } | null;
}

export interface DocumentSession {
  id: string;
  sourceFilename: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  errorMessage: string | null;
  resultAvailable: boolean;
}

export interface Transport {
  runtime(): Promise<RuntimeInfo>;
  models(): Promise<ModelInventory>;
  installModel(profileId: string): Promise<ModelInventory>;
  selectModel(profileId: string): Promise<ModelInventory>;
  uploadDocument(document?: File): Promise<DocumentSession | null>;
  document(sessionId: string): Promise<DocumentSession>;
  resultUrl(sessionId: string): string | null;
  saveResult(sessionId: string): Promise<void>;
}
