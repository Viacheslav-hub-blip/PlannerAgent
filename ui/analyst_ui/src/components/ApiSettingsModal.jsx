import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { getApiBase, setApiBase } from "../api.js";

export function ApiSettingsModal({ open, onClose }) {
  const [value, setValue] = useState("/api/v1");

  useEffect(() => {
    if (open) setValue(getApiBase());
  }, [open]);

  function save(event) {
    event.preventDefault();
    setApiBase(value);
    onClose();
  }

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={onClose}
        >
          <motion.form
            className="api-modal"
            onSubmit={save}
            initial={{ opacity: 0, scale: 0.94, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 20 }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" className="modal-close" onClick={onClose}>
              <X size={17} />
            </button>
            <div className="section-label">API settings</div>
            <h2>Базовый URL API</h2>
            <p>Для Vite dev обычно оставьте <code>/api/v1</code>. Proxy отправит запросы на backend 127.0.0.1:8000.</p>
            <label>
              <span>API Base</span>
              <input value={value} onChange={(event) => setValue(event.target.value)} />
            </label>
            <button type="submit" className="primary-cta">Сохранить</button>
          </motion.form>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
