import { BrowserRouter, Route, Routes } from "react-router-dom";
import { LoginGate } from "./LoginGate";
import { ProjectDetail } from "./pages/ProjectDetail";
import { ProjectList } from "./pages/ProjectList";

export default function App() {
  return (
    <BrowserRouter>
      <LoginGate>
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
        </Routes>
      </LoginGate>
    </BrowserRouter>
  );
}
