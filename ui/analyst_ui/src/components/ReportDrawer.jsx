import { AnimatePresence, motion } from "framer-motion";
import { FileText, Loader2, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ReportDrawer({ open, runId, report, meta, loading, error, onClose }) {
  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="drawer-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={onClose}
        >
          <motion.aside
            className="report-drawer"
            initial={{ opacity: 0, x: 42 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 42 }}
            transition={{ duration: 0.25 }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="report-drawer-header">
              <div>
                <div className="section-label">Final answer</div>
                <h2>Итоговый отчёт</h2>
              </div>
              <button type="button" className="modal-close" onClick={onClose}>
                <X size={18} />
              </button>
            </div>

            <div className="report-run-meta">
              <div><span>Run</span><code>{runId || "—"}</code></div>
              <div><span>Status</span><strong>{meta?.status || "—"}</strong></div>
              <div><span>Title</span><strong>{meta?.title || meta?.initial_user_query || "—"}</strong></div>
            </div>

            {loading ? (
              <div className="report-state">
                <Loader2 className="spin" size={20} />
                Загружаю итоговый отчёт…
              </div>
            ) : error ? (
              <div className="report-state report-state--error">{error}</div>
            ) : (
              <article className="report-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {report || "Финальный отчёт пока отсутствует."}
                </ReactMarkdown>
              </article>
            )}

            <div className="report-drawer-footer">
              <FileText size={15} />
              Финальный отчёт загружается напрямую из <code>/runs/&#123;run_id&#125;/result</code>.
            </div>
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
