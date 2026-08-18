import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { ProjectDetail } from "../types";

const POLL_MS = 2000;

/** Tải project và tự poll khi đang có run chạy.
 *
 *  Dừng poll ngay khi `run.is_active` false — không để timer chạy mãi. Backend
 *  cập nhật `step`/`step_status` hai lần mỗi bước nên 2 giây là đủ mượt
 *  (bước ngắn nhất vẫn kéo dài vài giây).
 */
export function useProject(projectId: string | undefined) {
  const [data, setData] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId) return null;
    try {
      const next = await api.getProject(projectId);
      setData(next);
      setError(null);
      return next;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      return null;
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      const next = await refresh();
      if (cancelled) return;
      if (next?.run?.is_active) {
        timer.current = window.setTimeout(tick, POLL_MS);
      }
    };
    tick();

    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  /** Gọi sau khi bấm Xử lý: khởi động lại vòng poll ngay, không đợi 2 giây. */
  const startPolling = useCallback(async () => {
    if (timer.current) window.clearTimeout(timer.current);
    const next = await refresh();
    if (next?.run?.is_active) {
      const tick = async () => {
        const latest = await refresh();
        if (latest?.run?.is_active) timer.current = window.setTimeout(tick, POLL_MS);
      };
      timer.current = window.setTimeout(tick, POLL_MS);
    }
  }, [refresh]);

  return { data, error, loading, refresh, startPolling };
}
