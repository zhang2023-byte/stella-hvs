import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, setSessionToken } from "./api";
import type { Bootstrap } from "./types";
import { EvaluatePage } from "./pages/EvaluatePage";
import { HistoryPage } from "./pages/HistoryPage";
import { ReviewPage } from "./pages/ReviewPage";
import { RunPage } from "./pages/RunPage";
import { SetupPage } from "./pages/SetupPage";
import { StandaloneRunPage } from "./pages/StandaloneRunPage";

const BootstrapContext = createContext<Bootstrap | null>(null);

export function useBootstrap() {
  const value = useContext(BootstrapContext);
  if (!value) throw new Error("bootstrap is not ready");
  return value;
}

const stages = [
  { path: "/setup", label: "01 配置" },
  { path: "/runs", label: "02 运行" },
  { path: "/review", label: "03 复核" },
  { path: "/evaluate", label: "04 评估" },
];

function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/setup" className="brand" aria-label="Stella Dev Console 首页">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span>
            <strong>STELLA</strong>
            <small>引导式 Dev Console</small>
          </span>
        </NavLink>
        <nav className="stage-nav" aria-label="Dev run 阶段">
          {stages.map((stage) => (
            <span
              key={stage.path}
              className={location.pathname.startsWith(stage.path) ? "stage-current" : ""}
            >
              {stage.label}
            </span>
          ))}
        </nav>
        <NavLink className="quiet-link" to="/history">历史记录</NavLink>
      </header>
      <main>{children}</main>
    </div>
  );
}

export function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api.bootstrap()
      .then((value) => {
        if (!live) return;
        setSessionToken(value.session_token);
        setBootstrap(value);
      })
      .catch((reason: Error) => live && setError(reason.message));
    return () => { live = false; };
  }, []);

  const context = useMemo(() => bootstrap, [bootstrap]);
  if (error) {
    return <div className="boot-state error-panel"><h1>控制台未能启动</h1><p>{error}</p></div>;
  }
  if (!context) {
    return <div className="boot-state"><span className="spinner" />正在读取本地 Dev 环境…</div>;
  }

  return (
    <BootstrapContext.Provider value={context}>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/setup" replace />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/runs/single/:campaignId/:runId" element={<StandaloneRunPage />} />
          <Route path="/runs/:groupId" element={<RunPage />} />
          <Route path="/review/:groupId" element={<ReviewPage />} />
          <Route path="/evaluate/:groupId" element={<EvaluatePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </Shell>
    </BootstrapContext.Provider>
  );
}
