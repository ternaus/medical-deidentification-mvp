import { useEffect, useMemo, useState } from "react";
import type { ReviewSession, RuntimeInfo } from "@medical-deid/contract";
import { selectTransport } from "./transport";
import "./styles.css";

export default function App() {
  const transport = useMemo(selectTransport, []);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [session, setSession] = useState<ReviewSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    transport.runtime().then(setRuntime).catch((reason: Error) => setError(reason.message));
  }, [transport]);

  async function openFixture() {
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      setSession(await transport.createReviewSession());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось открыть fixture");
    } finally {
      setBusy(false);
    }
  }

  async function sendFeedback(rating: "correct" | "incorrect") {
    if (!session) return;
    try {
      await transport.feedback(session.id, { rating });
      setFeedback(rating === "correct" ? "Спасибо, разметка подтверждена." : "Записано: требуется разбор.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить отзыв");
    }
  }

  async function deleteSession() {
    if (!session) return;
    await transport.removeSession(session.id);
    setSession(null);
    setFeedback(null);
  }

  const isReview = runtime?.mode === "review";

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">MEDICAL DEID · GREENFIELD</p>
          <h1>Проверка обезличивания</h1>
        </div>
        <span className={`status ${isReview ? "review" : "local"}`}>
          {isReview ? "Interface review" : "Local processing"}
        </span>
      </header>

      <section className="notice">
        <strong>{isReview ? "Синтетические данные only" : "Локальная обработка"}</strong>
        <span>
          {isReview
            ? "Это безопасный UI-срез. Произвольные медицинские файлы отключены до установки подписанного model package."
            : "Документ остаётся на этом устройстве; перед запуском worker проходит hardware и model preflight."}
        </span>
      </section>

      <section className="toolbar">
        <div>
          <h2>Рабочая область</h2>
          <p className="muted">Один документ за сессию · PDF, JPG, JPEG, PNG</p>
        </div>
        <button className="primary" disabled={busy} onClick={openFixture}>
          {busy ? "Открываю…" : "Открыть synthetic fixture"}
        </button>
      </section>

      {error && <p className="error">{error}</p>}
      {!session ? (
        <section className="empty card">
          <div className="empty-icon">＋</div>
          <h2>Документ ещё не выбран</h2>
          <p>Нажмите кнопку выше, чтобы проверить весь review-flow без реальных данных.</p>
        </section>
      ) : (
        <>
          <section className="comparison">
            <DocumentCard title="До" label={session.sourceLabel} text={session.sourceText} />
            <DocumentCard title="После" label="reconstructed-result.pdf" text={session.resultText} safe />
          </section>
          <section className="details card">
            <div className="details-head">
              <div>
                <p className="eyebrow">CHANGE LOG</p>
                <h2>{session.changes.length} изменения</h2>
              </div>
              <button className="ghost" onClick={deleteSession}>Удалить сессию</button>
            </div>
            <div className="change-list">
              {session.changes.map((change) => (
                <div className="change" key={`${change.source}-${change.reason}`}>
                  <span className="change-kind">{change.kind === "identifier" ? "ID" : "MASK"}</span>
                  <code>{change.source}</code>
                  <span className="arrow">→</span>
                  <code>{change.replacement}</code>
                  <span className="muted">{change.reason}</span>
                </div>
              ))}
            </div>
            <div className="feedback-row">
              <span>Результат выглядит корректно?</span>
              <button className="feedback" onClick={() => sendFeedback("correct")}>Да</button>
              <button className="feedback danger" onClick={() => sendFeedback("incorrect")}>Нужна проверка</button>
              {feedback && <span className="feedback-message">{feedback}</span>}
            </div>
          </section>
          {session.warnings.map((warning) => <p className="warning" key={warning}>⚠ {warning}</p>)}
        </>
      )}

      <footer>
        <span>app {runtime?.appVersion ?? "…"} · core {runtime?.coreVersion ?? "…"}</span>
        <span>{runtime?.modelStatus === "not_installed" ? "Model package не установлен" : runtime?.modelVersion}</span>
      </footer>
    </main>
  );
}

function DocumentCard({ title, label, text, safe = false }: { title: string; label: string; text: string; safe?: boolean }) {
  return (
    <article className={`document card ${safe ? "safe" : ""}`}>
      <div className="document-head">
        <div><span className="document-title">{title}</span><span className="muted">{label}</span></div>
        <span className="badge">{safe ? "Проверено" : "Источник"}</span>
      </div>
      <pre>{text}</pre>
    </article>
  );
}
