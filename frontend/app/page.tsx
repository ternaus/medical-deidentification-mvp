"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

type Session = {
  id: string;
  source_filename: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  result_available: boolean;
  feedback_submitted: boolean;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [sourcePreview, setSourcePreview] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<Session | null>(null);
  const [feedback, setFeedback] = useState("");
  const [feedbackState, setFeedbackState] = useState("");
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);

  const isProcessing = selected?.status === "queued" || selected?.status === "running";
  const resultUrl = selected ? `${apiBase}/api/sessions/${selected.id}/result` : null;

  useEffect(() => {
    void refreshSessions();
  }, []);

  useEffect(() => {
    if (!selected || !isProcessing) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshSelected(selected.id);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [isProcessing, selected]);

  useEffect(() => {
    return () => {
      if (sourcePreview) {
        URL.revokeObjectURL(sourcePreview);
      }
    };
  }, [sourcePreview]);

  const beforeIsPdf = file?.type === "application/pdf" || file?.name.toLowerCase().endsWith(".pdf");
  const statusText = useMemo(() => {
    if (!selected) return "";
    if (selected.status === "queued") return "Документ ждёт своей очереди.";
    if (selected.status === "running") return "Распознаём и анонимизируем документ.";
    if (selected.status === "completed") return "Готово. Проверьте результат и скачайте PDF.";
    return selected.error_message ?? "Обработка остановлена без выдачи файла.";
  }, [selected]);

  async function refreshSessions() {
    const response = await fetch(`${apiBase}/api/sessions`);
    if (!response.ok) return;
    const loaded = (await response.json()) as Session[];
    setSessions(loaded);
  }

  async function refreshSelected(sessionId: string) {
    const response = await fetch(`${apiBase}/api/sessions/${sessionId}`);
    if (!response.ok) return;
    const updated = (await response.json()) as Session;
    setSelected(updated);
    setSessions((current) => [updated, ...current.filter((session) => session.id !== updated.id)]);
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setFile(chosen);
    setSourcePreview(chosen ? URL.createObjectURL(chosen) : null);
    setMessage("");
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Сначала выберите PDF, JPG или PNG.");
      return;
    }
    setUploading(true);
    setMessage("");
    const body = new FormData();
    body.append("document", file);
    try {
      const response = await fetch(`${apiBase}/api/sessions`, { method: "POST", body });
      const payload = (await response.json()) as Session | { detail: string };
      if (!response.ok || !("id" in payload)) {
        setMessage("detail" in payload ? payload.detail : "Не удалось начать обработку.");
        return;
      }
      setSelected(payload);
      setSessions((current) => [payload, ...current.filter((session) => session.id !== payload.id)]);
      setFeedback("");
      setFeedbackState("");
    } catch {
      setMessage("Не удалось связаться с локальным приложением.");
    } finally {
      setUploading(false);
    }
  }

  async function submitFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !feedback.trim()) return;
    setFeedbackState("Сохраняем…");
    const response = await fetch(`${apiBase}/api/sessions/${selected.id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: feedback }),
    });
    if (response.ok) {
      setFeedbackState("Отзыв сохранён.");
      setFeedback("");
      await refreshSelected(selected.id);
      return;
    }
    setFeedbackState("Не удалось сохранить отзыв. Попробуйте ещё раз.");
  }

  async function removeSelected() {
    if (!selected) return;
    const response = await fetch(`${apiBase}/api/sessions/${selected.id}`, { method: "DELETE" });
    if (!response.ok) {
      setMessage("Сейчас этот документ удалить нельзя.");
      return;
    }
    setSessions((current) => current.filter((session) => session.id !== selected.id));
    setSelected(null);
    setFeedback("");
    setFeedbackState("");
  }

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">Локально на этом Mac</p>
        <h1>Анонимизация медицинских документов</h1>
        <p className="intro">
          Загрузите синтетический PDF, JPG или PNG. Результат появится здесь в виде нового PDF.
        </p>
      </section>

      <section className="upload-card" aria-labelledby="upload-heading">
        <h2 id="upload-heading">Новый документ</h2>
        <form onSubmit={upload}>
          <label className="file-picker">
            <span>{file ? file.name : "Выберите PDF, JPG или PNG"}</span>
            <input accept=".pdf,.jpg,.jpeg,.png" onChange={chooseFile} type="file" />
          </label>
          <button disabled={uploading} type="submit">
            {uploading ? "Загружаем…" : "Анонимизировать"}
          </button>
        </form>
        {message && <p className="message" role="status">{message}</p>}
      </section>

      {selected && (
        <section className="session-card" aria-live="polite">
          <div className="session-heading">
            <div>
              <p className="eyebrow">Текущий документ</p>
              <h2>{selected.source_filename}</h2>
            </div>
            <span className={`status status-${selected.status}`}>{statusText}</span>
          </div>

          {isProcessing && <div className="spinner" aria-label="Идёт обработка" />}

          <div className="comparison">
            <article>
              <h3>До</h3>
              {sourcePreview ? (
                beforeIsPdf ? (
                  <iframe src={sourcePreview} title="Исходный документ" />
                ) : (
                  <img alt="Исходный документ" src={sourcePreview} />
                )
              ) : (
                <p className="muted">Исходный просмотр доступен в той вкладке, где был выбран файл.</p>
              )}
            </article>
            <article>
              <h3>После</h3>
              {selected.result_available && resultUrl ? (
                <iframe src={resultUrl} title="Анонимизированный документ" />
              ) : (
                <p className="muted">Результат появится после безопасной проверки.</p>
              )}
            </article>
          </div>

          {selected.result_available && resultUrl && (
            <a className="download" href={resultUrl}>Скачать анонимизированный PDF</a>
          )}

          <form className="feedback" onSubmit={submitFeedback}>
            <label htmlFor="feedback">Что не так или чего не хватает?</label>
            <textarea
              id="feedback"
              onChange={(event) => setFeedback(event.target.value)}
              placeholder="Опишите проблему своими словами."
              rows={7}
              value={feedback}
            />
            <div className="feedback-actions">
              <button disabled={!feedback.trim()} type="submit">Отправить отзыв</button>
              {feedbackState && <span role="status">{feedbackState}</span>}
              <button className="delete" onClick={removeSelected} type="button">Удалить эту сессию</button>
            </div>
          </form>
        </section>
      )}

      <section className="recent" aria-labelledby="recent-heading">
        <h2 id="recent-heading">Недавние документы</h2>
        {sessions.length ? (
          <ul>
            {sessions.map((session) => (
              <li key={session.id}>
                <button onClick={() => void refreshSelected(session.id)} type="button">
                  <span>{session.source_filename}</span>
                  <small>{new Date(session.created_at).toLocaleString("ru-RU")}</small>
                  <small>{session.status === "completed" ? "Готово" : "В обработке"}</small>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Здесь появятся последние десять документов.</p>
        )}
      </section>
    </main>
  );
}
