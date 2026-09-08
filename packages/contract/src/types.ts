export const CONTRACT_VERSION = "1.0" as const;

export type RuntimeMode = "review" | "local";
export type SessionStatus = "ready" | "processing" | "completed" | "deleted" | "failed";

export interface RuntimeInfo {
  mode: RuntimeMode;
  processingEnabled: boolean;
  appVersion: string;
  coreVersion: string;
  ocrVersion: string;
  modelVersion: string | null;
  modelStatus: "not_installed" | "ready" | "incompatible";
  supportedFormats: string[];
}

export interface ChangeEntry {
  kind: "identifier" | "visual_mask";
  source: string;
  replacement: string;
  reason: string;
}

export interface ReviewSession {
  id: string;
  status: SessionStatus;
  sourceLabel: string;
  sourceText: string;
  resultText: string;
  changes: ChangeEntry[];
  warnings: string[];
  createdAt: string;
}

export interface FeedbackPayload {
  rating: "correct" | "incorrect";
  note?: string;
}

export interface Transport {
  runtime(): Promise<RuntimeInfo>;
  createReviewSession(): Promise<ReviewSession>;
  session(id: string): Promise<ReviewSession>;
  feedback(id: string, payload: FeedbackPayload): Promise<void>;
  removeSession(id: string): Promise<void>;
}
