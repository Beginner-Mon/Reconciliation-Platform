import { Check, Loader2, X } from "lucide-react";
import { ProgressBar } from "./ProgressBar";
import type { DocumentView, Progress, Step } from "../types";

/** Màn hình tiến trình — chiếm cả khung PHẢI khi đang xử lý.
 *
 *  Thanh loading, thông báo trạng thái và sơ đồ từng bước đều ở đây; sidebar
 *  trái chỉ đổi icon từng dòng.
 */

const STEPS: { key: Step; label: string }[] = [
  { key: "ocr", label: "OCR" },
  { key: "extract", label: "Trích xuất" },
  { key: "validate", label: "Kiểm tra" },
];

type StepState = "done" | "running" | "failed" | "waiting";

function stateOf(document: DocumentView, step: Step): StepState {
  const index = STEPS.findIndex((s) => s.key === step);
  const current = document.step ? STEPS.findIndex((s) => s.key === document.step) : -1;

  if (document.status === "VALIDATED") return "done";
  if (document.status === "PENDING" || current === -1) return "waiting";
  if (document.status === "FAILED") {
    if (index < current) return "done";
    return index === current ? "failed" : "waiting";
  }
  if (index < current) return "done";
  if (index > current) return "waiting";
  return document.step_status === "done" ? "done" : "running";
}

const DOT: Record<StepState, string> = {
  done: "border-emerald-500 bg-emerald-500 text-white",
  running: "border-sky-500 bg-sky-500 text-white animate-pulse",
  failed: "border-red-500 bg-red-500 text-white",
  waiting: "border-slate-300 bg-white text-slate-300",
};

function StepGlyph({ state }: { state: StepState }) {
  if (state === "done") return <Check size={14} strokeWidth={3} />;
  if (state === "running") return <Loader2 size={14} className="animate-spin" />;
  if (state === "failed") return <X size={14} strokeWidth={3} />;
  return <span className="h-1.5 w-1.5 rounded-full bg-current" />;
}

interface Props {
  documents: DocumentView[];
  progress: Progress;
  active: boolean;
}

export function WorkflowView({ documents, progress, active }: Props) {
  const failed = documents.filter((d) => d.status === "FAILED").length;

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <h2 className="text-lg font-semibold text-slate-800">
        {active
          ? `Đang xử lý ${progress.total_documents} chứng từ`
          : "Đã xử lý xong"}
      </h2>
      <div className="mt-3">
        <ProgressBar
          percent={progress.progress_percent}
          label={`${progress.progress_percent}% · ${progress.done_documents}/${progress.total_documents} xong${
            failed ? ` · ${failed} lỗi` : ""
          }`}
        />
      </div>

      <div className="mt-8 space-y-6">
        {documents.map((document) => {
          const states = STEPS.map((step) => stateOf(document, step.key));
          const retrying = (document.attempt ?? 1) > 1 && document.status === "PROCESSING";

          return (
            <div key={document.document_id}>
              <div className="text-sm font-medium text-slate-700">{document.file_name}</div>

              <div className="mt-2 flex items-center">
                {STEPS.map((step, index) => (
                  <div key={step.key} className="flex flex-1 items-center last:flex-none">
                    <div className="flex flex-col items-center">
                      <span
                        className={`flex h-7 w-7 items-center justify-center rounded-full border-2 ${DOT[states[index]]}`}
                      >
                        <StepGlyph state={states[index]} />
                      </span>
                      <span className="mt-1 text-xs text-slate-500">{step.label}</span>
                    </div>
                    {index < STEPS.length - 1 && (
                      <div
                        className={`mx-1 h-0.5 flex-1 ${
                          states[index] === "done" ? "bg-emerald-400" : "bg-slate-200"
                        }`}
                      />
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-1.5 h-4 text-xs">
                {document.status === "FAILED" ? (
                  <span className="text-red-600">Lỗi: {document.error}</span>
                ) : retrying ? (
                  <span className="text-amber-600">
                    Đang thử lại lần {document.attempt} (nhà cung cấp AI báo quá tải)
                  </span>
                ) : document.status === "VALIDATED" ? (
                  <span className="text-emerald-600">xong</span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 border-t border-slate-200 pt-4 text-sm text-slate-500">
        {active
          ? "Xong hết → hệ thống tự đối soát toàn project"
          : "Đã đối soát xong, xem tab Cảnh báo"}
      </div>
    </div>
  );
}
