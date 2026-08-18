import type { DocumentType, DocumentStatus, Severity, Step } from "./types";

const money = new Intl.NumberFormat("vi-VN");

export function formatMoney(value: unknown): string {
  if (typeof value !== "number") return String(value ?? "—");
  return money.format(value);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return money.format(value);
  return String(value);
}

export function formatDateTime(iso?: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  purchase_order: "Đơn đặt hàng",
  invoice: "Hóa đơn",
  acceptance_record: "Biên bản nghiệm thu",
};

export const STEP_LABEL: Record<Step, string> = {
  ocr: "đang đọc chữ (OCR)",
  extract: "đang trích xuất",
  validate: "đang kiểm tra",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Nghiêm trọng",
  high: "Cao",
  medium: "Trung bình",
  low: "Thấp",
};

/** Thứ tự này quyết định mâu thuẫn nào hiện trước. */
export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export const SEVERITY_STYLE: Record<Severity, { box: string; chip: string; icon: string }> = {
  critical: {
    box: "border-red-300 bg-red-50",
    chip: "bg-red-600 text-white",
    icon: "⛔",
  },
  high: {
    box: "border-orange-300 bg-orange-50",
    chip: "bg-orange-500 text-white",
    icon: "⚠",
  },
  medium: {
    box: "border-amber-300 bg-amber-50",
    chip: "bg-amber-500 text-white",
    icon: "●",
  },
  low: {
    box: "border-slate-300 bg-slate-50",
    chip: "bg-slate-500 text-white",
    icon: "○",
  },
};

export function statusLabel(status: DocumentStatus, step?: Step | null): string {
  if (status === "PENDING") return "chờ xử lý";
  if (status === "FAILED") return "lỗi";
  if (status === "VALIDATED") return "đã xử lý";
  if (status === "PROCESSING" && step) return STEP_LABEL[step];
  return "đang xử lý";
}

/** Ngưỡng dưới mức này thì tô cảnh báo — đo được từ spike: 0,38-0,44 đúng là chỗ đọc sai. */
export const LOW_CONFIDENCE = 0.75;
