import type {
  DevMeta,
  Extraction,
  OcrResult,
  ProcessResult,
  Project,
  ProjectDetail,
  Reconciliation,
  UploadTarget,
} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Không kết nối được tới ${BASE}. Dev server đã chạy chưa?`);
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

  requestUpload: (id: string, fileNames: string[]) =>
    request<{ documents: UploadTarget[] }>("POST", `/projects/${id}/documents`, {
      files: fileNames.map((file_name) => ({ file_name })),
    }),

  process: (id: string, options: { force?: boolean } = {}) =>
    request<ProcessResult>("POST", `/projects/${id}/process`, options),

  reconcile: (id: string) => request<Reconciliation>("POST", `/projects/${id}/reconcile`),

  getReconciliation: (id: string) =>
    request<Reconciliation>("GET", `/reconciliations/${id}`),

  getOcr: (projectId: string, documentId: string) =>
    request<OcrResult>("GET", `/projects/${projectId}/documents/${documentId}/ocr`),

  /** Chỉ dev server có route này. Production trả 404 → coi như AI thật. */
  getDevMeta: async (): Promise<DevMeta | null> => {
    try {
      return await request<DevMeta>("GET", "/__dev__");
    } catch {
      return null;
    }
  },

  editDocument: (projectId: string, documentId: string, fields: Partial<Extraction>) =>
    request<{ document: unknown; validation: unknown; reconciliation: Reconciliation }>(
      "PATCH",
      `/projects/${projectId}/documents/${documentId}`,
      { fields, reviewer: "poc-user" },
    ),

  approve: (reconciliationId: string) =>
    request<Reconciliation>("POST", `/reconciliations/${reconciliationId}/approve`, {
      reviewer: "poc-user",
    }),

  reject: (reconciliationId: string) =>
    request<Reconciliation>("POST", `/reconciliations/${reconciliationId}/reject`, {
      reviewer: "poc-user",
    }),
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
