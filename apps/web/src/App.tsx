import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "./components/layout/AppShell";
import { useLiveEvents } from "./hooks/useLiveEvents";
import { Dashboard } from "./routes/dashboard";
import { ClipsList } from "./routes/clips/index";
import { ClipDetail } from "./routes/clips/detail";
import { FrameDetailPage } from "./routes/clips/frame";
import { LabelingQueue } from "./routes/labeling/index";
import { LabelingFrame } from "./routes/labeling/frame";
import { ClassesList } from "./routes/classes/index";
import { ClassDetail } from "./routes/classes/detail";
import { ModelsPage } from "./routes/models";
import { TrainingPage } from "./routes/training";
import { MetricsPage } from "./routes/metrics";
import { SystemPage } from "./routes/system";
import { SettingsPage } from "./routes/settings";

function LiveEventsBridge() {
  useLiveEvents();
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <LiveEventsBridge />
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/clips" element={<ClipsList />} />
          <Route path="/clips/:id" element={<ClipDetail />} />
          <Route path="/clips/:id/frames/:frameId" element={<FrameDetailPage />} />
          <Route path="/labeling" element={<LabelingQueue />} />
          <Route path="/labeling/:fid" element={<LabelingFrame />} />
          <Route path="/classes" element={<ClassesList />} />
          <Route path="/classes/:id" element={<ClassDetail />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/training" element={<TrainingPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/system/disk" element={<SystemPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </AppShell>
      <Toaster richColors position="bottom-right" />
    </BrowserRouter>
  );
}
