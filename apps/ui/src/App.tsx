import { useCallback, useEffect, useMemo, useState } from "react";
import type { DocumentSession, ModelInventory, ModelProfile, RuntimeInfo } from "@medical-deid/contract";
import { isDesktopTransport, selectTransport } from "./transport";
import "./styles.css";

const POLL_INTERVAL_MS = 1000;

export default function App() {
  const transport = useMemo(selectTransport, []);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [models, setModels] = useState<ModelInventory | null>(null);
  const [session, setSession] = useState<DocumentSession | null>(null);
  const [sessions, setSessions] = useState<DocumentSession[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showModelSettings, setShowModelSettings] = useState(false);

  const refresh = useCallback(async () => {
    const [nextRuntime, nextModels, nextSessions] = await Promise.all([
      transport.runtime(),
      transport.models(),
      transport.documents(),
    ]);
    setRuntime(nextRuntime);
    setModels(nextModels);
    setSessions(nextSessions);
    setSession(
      (current) => nextSessions.find((candidate) => candidate.id === current?.id) ?? nextSessions[0] ?? null,
    );
  }, [transport]);

  useEffect(() => {
    refresh().catch((reason: unknown) => setError(messageFrom(reason)));
  }, [refresh]);

  useEffect(() => {
    if (!models?.profiles.some((profile) => profile.state === "downloading")) return;
    const timer = window.setInterval(() => {
      refresh().catch((reason: unknown) => setError(messageFrom(reason)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [models, refresh]);

  useEffect(() => {
    if (!session || session.status === "completed" || session.status === "failed") return;
    const timer = window.setInterval(() => {
      transport
        .document(session.id)
        .then((nextSession) => {
          setSession(nextSession);
          setSessions((current) => updateSession(current, nextSession));
        })
        .catch((reason: unknown) => setError(messageFrom(reason)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [session, transport]);

  async function install(profile: ModelProfile) {
    setBusy(profile.id);
    setError(null);
    try {
      setModels(await transport.installModel(profile.id));
      await refresh();
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(null);
    }
  }

  async function select(profile: ModelProfile) {
    setBusy(profile.id);
    setError(null);
    try {
      setModels(await transport.selectModel(profile.id));
      await refresh();
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(null);
    }
  }

  async function upload(file?: File) {
    setBusy("upload");
    setError(null);
    try {
      const nextSession = await transport.uploadDocument(file);
      if (nextSession) {
        setSession(nextSession);
        setSessions((current) => updateSession(current, nextSession));
      }
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(null);
    }
  }

  const ready = runtime?.processingEnabled === true;
  const desktop = isDesktopTransport();
  const downloading = models?.profiles.some((profile) => profile.state === "downloading") ?? false;

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">MEDICAL DEID · LOCAL</p>
          <h1>Обезличивание документов на этом устройстве</h1>
        </div>
        <span className={`status ${ready ? "ready" : "setup"}`}>{ready ? "Готово" : "Нужна настройка"}</span>
      </header>

      <section className="notice">
        <strong>{ready ? "Модели установлены" : "Сначала нужно скачать модели"}</strong>
        <span>
          {ready
            ? "Документ анализируется локально и не отправляется на сервер."
            : "Выберите профиль и нажмите «Скачать». Приложение проверит файлы перед включением анализа."}
        </span>
      </section>

      {error && <p className="error">{error}</p>}

      {(!ready || showModelSettings) && models && (
        <section className="card setup-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{ready ? "НАСТРОЙКИ" : "ШАГ 1"}</p>
              <h2>{ready ? "Выберите другую модель" : "Модели и ускорение"}</h2>
            </div>
            <span className="accelerator">{models.runtime.label} · {runtime?.accelerator?.state === "ready" ? "готово" : "будет установлено"}</span>
          </div>
          <p className="muted setup-copy">
            В комплект установки входят OCR и выбранная Qwen. Лёгкий профиль подходит для первого запуска;
            более тяжёлый можно поставить позднее в настройках.
          </p>
          <div className="profiles">
            {models.profiles.map((profile) => (
              <ModelCard
                key={profile.id}
                profile={profile}
                downloading={downloading}
                busy={busy === profile.id}
                selected={models.selectedProfile === profile.id}
                onInstall={() => install(profile)}
                onSelect={() => select(profile)}
              />
            ))}
          </div>
          {models.preflight && models.preflight.blockers.length > 0 && (
            <p className="warning">Перед анализом: {models.preflight.blockers.map(preflightLabel).join(" · ")}</p>
          )}
        </section>
      )}

      {ready && (
        <section className="card upload-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">АНАЛИЗ</p>
              <h2>Загрузите документ</h2>
            </div>
            <span className="accelerator">{runtime?.accelerator?.label ?? "Локальный runtime"}</span>
          </div>
          <p className="muted">PDF, JPG, JPEG или PNG до 25 МБ.</p>
          <button className="secondary model-settings" onClick={() => setShowModelSettings((visible) => !visible)}>
            {showModelSettings ? "Скрыть модели" : "Модели и ускорение"}
          </button>
          {desktop ? (
            <button className="file-button" disabled={busy === "upload"} onClick={() => upload()}>
              {busy === "upload" ? "Добавляю в очередь…" : "Выбрать документ"}
            </button>
          ) : (
            <label className={`file-button ${busy === "upload" ? "disabled" : ""}`}>
              <input
                accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                disabled={busy === "upload"}
                onChange={(event) => upload(event.currentTarget.files?.[0])}
                type="file"
              />
              {busy === "upload" ? "Добавляю в очередь…" : "Выбрать документ"}
            </label>
          )}
        </section>
      )}

      {sessions.length > 0 && session && (
        <section className="card session-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">ДОКУМЕНТЫ</p>
              <h2>Недавние документы</h2>
            </div>
          </div>
          <div className="session-list">
            {sessions.map((candidate) => (
              <button
                className={`session-item ${candidate.id === session.id ? "selected" : ""}`}
                key={candidate.id}
                onClick={() => setSession(candidate)}
              >
                <span>{candidate.sourceFilename}</span>
                <span>{sessionLabel(candidate)}</span>
              </button>
            ))}
          </div>
          <SessionStatus
            session={session}
            resultUrl={transport.resultUrl(session.id)}
            onSave={() => transport.saveResult(session.id)}
          />
        </section>
      )}

      <footer>
        <span>app {runtime?.appVersion ?? "…"} · core {runtime?.coreVersion ?? "…"}</span>
        <span>{runtime?.modelVersion ?? "Qwen ещё не выбрана"}</span>
      </footer>
    </main>
  );
}

function ModelCard({
  profile,
  downloading,
  busy,
  selected,
  onInstall,
  onSelect,
}: {
  profile: ModelProfile;
  downloading: boolean;
  busy: boolean;
  selected: boolean;
  onInstall: () => void;
  onSelect: () => void;
}) {
  const progress = profile.totalBytes > 0 ? Math.min(100, (profile.downloadedBytes / profile.totalBytes) * 100) : 0;
  return (
    <article className={`profile ${selected ? "selected" : ""}`}>
      <div className="profile-title">
        <div>
          <strong>{profile.label}</strong>
          {profile.recommended && <span className="recommended">рекомендуется</span>}
        </div>
        <span>{formatBytes(profile.sizeBytes)}</span>
      </div>
      <p>{profile.description}</p>
      <p className="muted">от {formatBytes(profile.minMemoryBytes)} RAM · {formatBytes(profile.minFreeDiskBytes)} свободного места</p>
      {profile.state === "downloading" && (
        <div className="download-progress">
          <div><span>{profile.currentAsset ?? "Подготавливаю"}</span><span>{Math.round(progress)}%</span></div>
          <progress max="100" value={progress} />
        </div>
      )}
      {profile.state === "failed" && <p className="error">{profile.error ?? "Скачивание не завершилось"}</p>}
      {profile.state === "ready" ? (
        <button className="secondary" disabled={selected || busy} onClick={onSelect}>
          {selected ? "Выбрана" : "Использовать эту модель"}
        </button>
      ) : (
        <button className="primary" disabled={downloading || busy} onClick={onInstall}>
          {busy ? "Запускаю…" : "Скачать"}
        </button>
      )}
    </article>
  );
}

function SessionStatus({ session, resultUrl, onSave }: { session: DocumentSession; resultUrl: string | null; onSave: () => void }) {
  if (session.status === "completed") {
    return resultUrl ? <p className="success">Готово. <a href={resultUrl}>Скачать обезличенный PDF</a></p> : <p className="success">Готово. <button className="download-link" onClick={onSave}>Сохранить обезличенный PDF</button></p>;
  }
  if (session.status === "failed") return <p className="error">{session.errorMessage ?? "Анализ не завершился безопасно."}</p>;
  return <p className="processing">{session.status === "queued" ? "Документ в очереди…" : "OCR и поиск идентификаторов выполняются…"}</p>;
}

function formatBytes(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(bytes < 10 * 1024 ** 3 ? 1 : 0)} ГБ`;
}

function preflightLabel(blocker: string) {
  return {
    insufficient_memory: "недостаточно RAM",
    insufficient_disk: "недостаточно свободного места",
    model_not_installed: "модель не скачана",
    ocr_not_installed: "OCR не скачан",
    runtime_not_installed: "runtime не скачан",
    unsupported_platform: "неподдерживаемая платформа",
  }[blocker] ?? blocker;
}

function messageFrom(reason: unknown) {
  return reason instanceof Error ? reason.message : "Не удалось выполнить операцию.";
}

function updateSession(sessions: DocumentSession[], nextSession: DocumentSession) {
  return [nextSession, ...sessions.filter((candidate) => candidate.id !== nextSession.id)];
}

function sessionLabel(session: DocumentSession) {
  if (session.status === "completed") return "Готово";
  if (session.status === "failed") return "Ошибка";
  return session.status === "running" ? "Обработка" : "В очереди";
}
