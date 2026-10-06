import type {
  Extraction,
  OcrResult,
  ProcessOptions,
  ProcessResult,
  Project,
  ProjectDetail,
  Reconciliation,
  UploadTarget,
} from "./types";
import { dangXuat, layToken } from "./auth";

const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = body === undefined ? {} : { "Content-Type": "application/json" };
  try {
    const token = await layToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    // auth chưa sẵn sàng, bỏ qua
  }

  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Không kết nối được tới ${BASE}. Dev server đã chạy chưa?`);
  }

  if (response.status === 401) {
    try {
      await dangXuat();
    } catch {
      // bỏ qua
    }
  }

  const text = await response.text();
  const parsed = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new ApiError(response.status, parsed.error ?? `Lỗi ${response.status}`);
  }
  return parsed as T;
}

export const api = {
  listProjects: () => request<{ items: Project[] }>("GET", "/projects"),

  createProject: (name: string, description = "") =>
    request<Project>("POST", "/projects", { name, description }),

  getProject: (id: string) => request<ProjectDetail>("GET", `/projects/${id}`),

  deleteProject: (id: string) =>
    request<{
      project_id: string;
      deleted: { documents: number; reconciliations: number; runs: number; s3_objects: number };
    }>("DELETE", `/projects/${id}`),

  requestUpload: (id: string, fileNames: string[]) =>
    request<{ documents: UploadTarget[] }>("POST", `/projects/${id}/documents`, {
      files: fileNames.map((file_name) => ({ file_name })),
    }),

  /** Bỏ trống `document_ids` là chạy cả project; truyền vào là chạy đúng chừng
   *  đó chứng từ. `force` bỏ qua cache (chứng từ đã VALIDATED). */
  process: (id: string, options: ProcessOptions = {}) =>
    request<ProcessResult>("POST", `/projects/${id}/process`, options),

  stopProcess: (id: string) =>
    request<{ project_id: string; run_id: string; cancel_requested_at: string }>(
      "POST",
      `/projects/${id}/process/stop`,
    ),

  reconcile: (id: string) => request<Reconciliation>("POST", `/projects/${id}/reconcile`),

  getReconciliation: (id: string) =>
    request<Reconciliation>("GET", `/reconciliations/${id}`),

  getOcr: (projectId: string, documentId: string) =>
    request<OcrResult>("GET", `/projects/${projectId}/documents/${documentId}/ocr`),

  editDocument: (projectId: string, documentId: string, fields: Partial<Extraction>) =>
    request<{ document: unknown; validation: unknown; reconciliation: Reconciliation }>(
      "PATCH",
      `/projects/${projectId}/documents/${documentId}`,
      { fields },
    ),

  review: (reconciliationId: string, decision: "APPROVED" | "REJECTED") =>
    request<Reconciliation>("POST", `/reconciliations/${reconciliationId}/review`, {
      decision,
    }),

  deleteDocument: (projectId: string, documentId: string) =>
    request<{ project_id: string; document_id: string; reconciliation: Reconciliation | null }>(
      "DELETE",
      `/projects/${projectId}/documents/${documentId}`,
    ),

  setAnchor: (projectId: string, documentId: string) =>
    request<{ project_id: string; anchor_document_ids: string[]; reconciliation: Reconciliation | null }>(
      "PUT",
      `/projects/${projectId}/anchor`,
      { document_id: documentId },
    ),
};

/** Upload thẳng lên S3 bằng presigned POST.
 *
 *  Dùng POST + FormData chứ KHÔNG phải PUT: đây là "simple request" theo CORS
 *  nên trình duyệt không gửi preflight OPTIONS. Presigned PUT thì có, và
 *  preflight đó bị S3 giả lập từ chối.
 *
 *  Thứ tự quan trọng: mọi trường trong `fields` phải được append TRƯỚC `file`.
 *  S3 bỏ qua tất cả những gì đứng sau `file`.
 */
export async function uploadFile(target: UploadTarget, file: File): Promise<void> {
  if (file.size > target.max_bytes) {
    throw new ApiError(
      413,
      `${file.name} nặng ${(file.size / 1024 / 1024).toFixed(1)}MB, vượt giới hạn ${
        target.max_bytes / 1024 / 1024
      }MB`,
    );
  }

  const form = new FormData();
  for (const [key, value] of Object.entries(target.upload.fields)) {
    form.append(key, value);
  }
  form.append("file", file);

  const response = await fetch(target.upload.url, { method: "POST", body: form });
  if (!response.ok) {
    throw new ApiError(response.status, `Upload ${file.name} thất bại (${response.status})`);
  }
}
