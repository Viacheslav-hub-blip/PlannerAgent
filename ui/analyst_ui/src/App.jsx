import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { ApiSettingsModal } from "./components/ApiSettingsModal.jsx";
import { CommandCenter } from "./components/CommandCenter.jsx";
import { LiveRunWorkspace } from "./components/LiveRunWorkspace.jsx";
import { TopNav } from "./components/TopNav.jsx";
import { useLiveRun } from "./hooks/useLiveRun.js";

export default function App() {
  const liveRun = useLiveRun();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const hasWorkspace = liveRun.phase !== "idle";

  return (
    <div className="app-shell">

      <TopNav onOpenSettings={() => setSettingsOpen(true)} runId={liveRun.runId} />

      <main className={hasWorkspace ? "app-main app-main--workspace" : "app-main"}>
        <AnimatePresence mode="wait">
          {!hasWorkspace ? (
            <CommandCenter key="command" onSubmit={liveRun.start} />
          ) : (
            <LiveRunWorkspace key="workspace" liveRun={liveRun} />
          )}
        </AnimatePresence>
      </main>

      <ApiSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
