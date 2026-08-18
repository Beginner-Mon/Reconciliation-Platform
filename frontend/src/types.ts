/** Kiểu dữ liệu API trả về — khớp backend/api/views.py và backend/core/rules.py.
 *  Đây cũng là tài liệu API cho báo cáo kỹ thuật. */

export type DocumentStatus =
  | "PENDING"
  | "PROCESSING"
  | "OCR_DONE"
  | "EXTRACTED"
  | "VALIDATED"
  | "FAILED";

export type Step = "ocr" | "extract" | "validate";
export type StepStatus = "running" | "done" | "failed";
export type Severity = "critical" | "high" | "medium" | "low";
export type DocumentType = "purchase_order" | "invoice" | "acceptance_record";

export interface LineItem {
  item_name: string;
  quantity: number;
  unit?: string | null;
  unit_price?: number | null;
}

/** Dữ liệu AI trích xuất. Trường thay đổi theo loại chứng từ nên để mở. */
export interface Extraction {
  document_type?: DocumentType;
  vendor?: string;
  buyer?: string;
  currency?: string;
  po_number?: string;
  invoice_number?: string;
  record_number?: string;
  po_date?: string;
  invoice_date?: string;
  record_date?: string;
  items?: LineItem[];
  subtotal?: number;
  tax_amount?: number;
  total_amount?: number;
  [key: string]: unknown;
}

export interface Validation {
  valid: boolean;
  schema_errors: string[];
  rule_errors: string[];
}

export interface DocumentView {
  document_id: string;
  project_id: string;
  file_name: string;
  file_type?: string;
  size_bytes?: number;
  uploaded_at?: string;
  updated_at?: string;
  status: DocumentStatus;
  step?: Step | null;
  step_status?: StepStatus | null;
  attempt?: number;
  document_type?: DocumentType;
  po_number?: string;
  extraction?: Extraction;
  /** confidence THẬT từ OCR — dùng để tô trường AI đọc không chắc. */
  confidence?: Record<string, number>;
  validation?: Validation;
  edited_fields?: string[];
  edited_at?: string;
  error?: string | null;
  view_url?: string;
}

export interface Project {
  project_id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at?: string;
  document_count?: number;
  processing_run_id?: string;
  latest_reconciliation_id?: string;
}

export interface Progress {
  total_documents: number;
  done_documents: number;
  failed_documents: number;
  total_steps: number;
  done_steps: number;
  progress_percent: number;
}

export interface Run extends Progress {
  run_id: string;
  status: string;
  is_active: boolean;
  document_ids: string[];
  started_at?: string;
  finished_at?: string;
  error?: string | null;
}

export interface DiscrepancyValue {
  document_id: string;
  document_type: DocumentType;
  value: unknown;
}

export interface Discrepancy {
  rule_id: string;
  field: string;
  severity: Severity;
  values: DiscrepancyValue[];
  difference?: number | null;
  explanation: string;
}

export interface Reconciliation {
  reconciliation_id: string;
  project_id: string;
  created_at: string;
  document_ids: string[];
  discrepancy_count: number;
  severity_summary: Partial<Record<Severity, number>>;
  status: "PENDING_REVIEW" | "APPROVED" | "REJECTED";
  review?: { decision?: string | null; reviewer?: string | null; reviewed_at?: string | null };
  discrepancies?: Discrepancy[];
}

export interface ProjectDetail {
  project: Project;
  run: Run | null;
  progress: Progress;
  documents: DocumentView[];
  latest_reconciliation: Reconciliation | null;
}

/** Presigned POST — gửi FormData, KHÔNG phải PUT. Xem common/s3.py. */
export interface UploadTarget {
  document_id: string;
  file_name: string;
  s3_key: string;
  content_type: string;
  upload: { url: string; fields: Record<string, string> };
  max_bytes: number;
}

/** Text OCR thô — GET /projects/{id}/documents/{doc}/ocr */
export interface OcrResult {
  document_id: string;
  file_name: string;
  text: string;
  pages: {
    page_number: number;
    mean_token_confidence?: number | null;
    token_count?: number;
    key_value_pairs?: { key: string; value: string; confidence?: number | null }[];
    tables?: { rows: { cells: string[] }[] }[];
  }[];
}

/** GET /__dev__ — CHỈ dev server có. 404 nghĩa là đang chạy production. */
export interface DevMeta {
  fake_ai: boolean;
  latency: number;
}

export interface ProcessResult {
  project_id: string;
  run_id: string | null;
  processing: DocumentView[];
  skipped: { document_id: string; file_name: string; reason: string }[];
  message?: string;
}
