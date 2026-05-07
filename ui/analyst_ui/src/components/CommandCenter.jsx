import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles } from "lucide-react";

const EXAMPLES = [
  "Разбери сработку по event_id и объясни причину блокировки.",
  "Проверь, является ли операция обычной для клиента.",
];

export function CommandCenter({ onSubmit }) {
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [userId, setUserId] = useState("");

  function submit(event) {
    event.preventDefault();
    onSubmit({ query, sessionId, userId });
  }

  return (
    <motion.section
      className="start-page"
      initial={{ opacity: 0, y: 18, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -14, scale: 0.99 }}
      transition={{ duration: 0.42, ease: [0.2, 0.85, 0.2, 1] }}
    >
      <form className="start-card" onSubmit={submit}>
        <div className="start-kicker">
          <Sparkles size={16} />
          Research Agent
        </div>

        <h1>Что нужно проанализировать?</h1>
        <p className="start-subtitle">
          Опишите задачу обычным языком. Агент сам построит план, выполнит шаги и покажет ход работы на графе.
        </p>

        <textarea
          className="start-textarea"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Например: разбери сработку по event_id=... и объясни, обычная это операция или подозрительная"
          rows={7}
          autoFocus
        />

        <div className="start-examples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="start-example"
              onClick={() => setQuery(example)}
            >
              {example}
            </button>
          ))}
        </div>

        <details className="start-advanced">
          <summary>Дополнительные параметры</summary>
          <div className="start-advanced-grid">
            <label>
              <span>Session ID</span>
              <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="optional" />
            </label>
            <label>
              <span>User ID</span>
              <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="optional" />
            </label>
          </div>
        </details>

        <button type="submit" className="primary-cta start-submit">
          Запустить анализ
          <ArrowRight size={18} />
        </button>
      </form>
    </motion.section>
  );
}
