import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { coCognito } from "./auth";

const apiUrl = import.meta.env.VITE_API_URL ?? "";
function isLocalApiUrl(url: string): boolean {
  if (!url) return true;
  try {
    const h = new URL(url).hostname;
    return h === "127.0.0.1" || h === "localhost" || h === "::1";
  } catch {
    return url.includes("127.0.0.1") || url.includes("localhost");
  }
}
const isLocalApi = isLocalApiUrl(apiUrl);

if (!coCognito() && !isLocalApi) {
  const root = document.getElementById("root");
  if (root) {
    root.innerHTML =
      '<div style="max-width:600px;margin:80px auto;padding:24px;border:1px solid #e2e8f0;border-radius:8px;font-family:system-ui">' +
      '<h1 style="font-size:18px;font-weight:600">Thiếu cấu hình Cognito</h1>' +
      '<p style="margin-top:8px;color:#64748b">VITE_COGNITO_USER_POOL_ID / VITE_COGNITO_CLIENT_ID chưa được cấu hình mà VITE_API_URL lại trỏ ra ngoài localhost. App từ chối khởi động để tránh gọi API production không có token.</p>' +
      "<p style=\"margin-top:12px;font-size:14px;color:#334155\">Sửa <code>.env</code> hoặc đặt <code>VITE_API_URL=http://127.0.0.1:8000</code> cho dev.</p>" +
      "</div>";
  }
} else {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
