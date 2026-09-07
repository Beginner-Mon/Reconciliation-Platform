import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Circle,
  Loader2,
  Play,
  Plus,
  RotateCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { DocumentView, OcrEngineChoice } from "../types";

/** Sidebar: danh sách file, nút Xử lý cả project, và nút chạy lại TỪNG file.
 *
 *  Nút chạy lại mở menu chọn engine OCR. Đây là cách duy nhất so hai engine
 *  trên CÙNG một chứng từ — engine trước đây là biến môi trường của tiến trình
 *  nên cả project buộc phải dùng chung một engine.
 *
 *  Không đặt thanh tiến độ hay thông báo trạng thái ở đây — mọi thứ thể hiện
 *  quá trình xử lý đều nằm ở khung phải.
 */

function StatusIcon({ document }: { document: DocumentView }) {
  if (document.status === "FAILED") return <X size={16} className="text-red-600" />;
  if (document.status === "VALIDATED") return <Check size={16} className="text-emerald-600" />;
  if (document.status === "PENDING") return <Circle size={14} className="text-slate-400" />;
  return <Loader2 size={16} className="animate-spin text-sky-600" />;
}

interface Props {
  projectName: string;
  documents: DocumentView[];
  selectedId: string | null;
  running: boolean;
  busy: boolean;
  engines: readonly OcrEngineChoice[];
  defaultEngine: string;
  onSelect: (document: DocumentView) => void;
  onUpload: (files: FileList) => void;
  onProcess: () => void;
  onRerun: (document: DocumentView, engine: string) => void;
}

export function DocumentSidebar({
  projectName,
  documents,
  selectedId,
  running,
  busy,
  engines,
  defaultEngine,
  onSelect,
  onUpload,
  onProcess,
  onRerun,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  /** document_id đang mở menu chọn engine, null là không mở cái nào. */
  const [menuFor, setMenuFor] = useState<string | null>(null);

  // Bấm ra ngoài hoặc Esc thì đóng menu. Thiếu cái này thì menu dính lại khi
  // người dùng chuyển sang chứng từ khác.
  useEffect(() => {
    if (!menuFor) return;
    const close = () => setMenuFor(null);
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.document.addEventListener("click", close);
    window.document.addEventListener("keydown", onKey);
    return () => {
      window.document.removeEventListener("click", close);
      window.document.removeEventListener("keydown", onKey);
    };
  }, [menuFor]);

  const defaultLabel = defaultEngine ? ` (mặc định: ${defaultEngine})` : "";

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <a href="/" className="flex items-center gap-1 text-sm text-sky-700 hover:underline">
          <ArrowLeft size={14} /> Danh sách project
        </a>
        <h1 className="mt-1 truncate font-semibold text-slate-800" title={projectName}>
          {projectName}
        </h1>
      </div>

      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-xs font-semibold tracking-wide text-slate-500">
          CHỨNG TỪ ({documents.length})
        </span>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.tiff"
          onChange={(e) => e.target.files && onUpload(e.target.files)}
          className="hidden"
        />
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy || running}
          title="Thêm chứng từ"
          aria-label="Thêm chứng từ"
          className="flex h-6 w-6 items-center justify-center rounded border border-slate-300 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          <Plus size={14} strokeWidth={2.5} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {documents.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-slate-500">
            Chưa có chứng từ.
            <br />
            Bấm nút <Plus size={12} className="inline" /> để tải lên.
          </p>
        ) : (
          documents.map((document) => {
            const selected = document.document_id === selectedId;
            const menuOpen = menuFor === document.document_id;
            return (
              <div
                key={document.document_id}
                className={`relative flex items-center border-l-2 pr-2 transition ${
                  selected
                    ? "border-sky-500 bg-sky-50"
                    : "border-transparent hover:bg-slate-50"
                }`}
              >
                <button
                  onClick={() => onSelect(document)}
                  className={`flex min-w-0 flex-1 items-center gap-2 py-2.5 pl-4 text-left text-sm ${
                    selected ? "text-slate-900" : "text-slate-700"
                  }`}
                >
                  <span className="flex w-4 shrink-0 justify-center">
                    <StatusIcon document={document} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={document.file_name}>
                      {document.file_name}
                    </span>
                    {/* Engine đã chạy cho CHỨNG TỪ NÀY — hai chứng từ trong cùng
                        project có thể khác nhau, nên phải hiện ở từng dòng. */}
                    {document.ocr_engine && (
                      <span className="mt-0.5 block truncate text-xs text-slate-400">
                        {document.ocr_engine}
                      </span>
                    )}
                  </span>
                </button>

                <button
                  onClick={(event) => {
                    event.stopPropagation();
                    setMenuFor(menuOpen ? null : document.document_id);
                  }}
                  disabled={busy || running || engines.length === 0}
                  title="Chạy lại chứng từ này với engine khác"
                  aria-label="Chạy lại chứng từ này"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 transition hover:bg-white hover:text-sky-700 disabled:opacity-30"
                >
                  <RotateCw size={14} />
                </button>

                {menuOpen && (
                  <div
                    onClick={(event) => event.stopPropagation()}
                    className="absolute right-2 top-full z-20 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
                  >
                    <p className="border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-500">
                      CHẠY LẠI VỚI
                    </p>
                    {engines.map((engine) => (
                      <button
                        key={engine.name}
                        onClick={() => {
                          setMenuFor(null);
                          onRerun(document, engine.name);
                        }}
                        className="block w-full px-3 py-2 text-left text-sm transition hover:bg-slate-50"
                      >
                        <span className="flex items-center gap-1.5 font-medium text-slate-800">
                          {engine.name}
                          {engine.name === document.ocr_engine && (
                            <span className="text-xs font-normal text-slate-400">
                              · đang dùng
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">
                          {engine.label}
                        </span>
                        {/* Cảnh báo đặt NGAY chỗ chọn, không chôn trong tài
                            liệu: đo trên hoá đơn thật thì Textract mất gần hết
                            dấu tiếng Việt, dù số vẫn đọc đúng. */}
                        {!engine.supportsVietnamese && (
                          <span className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                            <AlertTriangle size={11} /> không hỗ trợ tiếng Việt
                          </span>
                        )}
                      </button>
                    ))}
                    <p className="border-t border-slate-100 bg-slate-50 px-3 py-1.5 text-xs text-slate-500">
                      Chạy lại là gọi AI lần nữa và tốn tiền lần nữa.
                    </p>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="border-t border-slate-200 p-3">
        <button
          onClick={onProcess}
          disabled={busy || running || documents.length === 0}
          title={`Xử lý chứng từ chưa chạy${defaultLabel}`}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-sky-600 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
        >
          {running ? (
            <>
              <Loader2 size={16} className="animate-spin" /> Đang chạy…
            </>
          ) : (
            <>
              <Play size={16} /> Xử lý
            </>
          )}
        </button>
        {defaultEngine && (
          <p className="mt-1.5 text-center text-xs text-slate-400">
            engine mặc định: {defaultEngine}
          </p>
        )}
      </div>
    </aside>
  );
}
