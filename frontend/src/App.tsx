import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ProjectDetail } from "./pages/ProjectDetail";
import { ProjectList } from "./pages/ProjectList";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
      </Routes>
    </BrowserRouter>
  );
}
