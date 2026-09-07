import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  Circle,
  Loader2,
  Play,
  Plus,
  RotateCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DEFAULT_OCR_ENGINE, OCR_ENGINES } from "../format";
import type { DocumentView } from "../types";

/** Sidebar: danh sách chứng từ có chọn nhiều, và HAI hành động của hệ thống.
 *
 *  Hai hành động đó khác nhau ở chỗ tốn tiền hay không:
 *
 *    Xử lý       đọc chữ -> trích xuất -> kiểm tra -> đối chiếu   GỌI AI, tốn tiền
 *    Đối chiếu   chỉ so các chứng từ với nhau                     miễn phí
 *
 *  "Xử lý tất cả" chỉ là trường hợp không chọn gì — không phải một nút riêng.
 *  Nhờ vậy chạy 1, chạy 3 hay chạy hết đều là cùng một thao tác.
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
  checkedIds: string[];
  running: boolean;
  busy: boolean;
  canReconcile: boolean;
  onSelect: (document: DocumentView) => void;
  onToggle: (documentId: string) => void;
  onToggleAll: () => void;
  onUpload: (files: FileList) => void;
  onProcess: (engine: string) => void;
  onReconcile: () => void;
}

export function DocumentSidebar({
  projectName,
  documents,
  selectedId,
  checkedIds,
  running,
  busy,
  canReconcile,
  onSelect,
  onToggle,
  onToggleAll,
  onUpload,
  onProcess,
  onReconcile,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [engine, setEngine] = useState<string>(DEFAULT_OCR_ENGINE);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.document.addEventListener("click", close);
    window.document.addEventListener("keydown", onKey);
    return () => {
      window.document.removeEventListener("click", close);
      window.document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const checked = new Set(checkedIds);
  const soChon = checked.size;
  const tatCa = documents.length > 0 && soChon === documents.length;
  const khoa = busy || running || documents.length === 0;

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

      <div className="flex items-center justify-between border-b border-slate-100 py-2 pl-3 pr-4">
        <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold tracking-wide text-slate-500">
          <input
            type="checkbox"
            checked={tatCa}
            onChange={onToggleAll}
            disabled={documents.length === 0}
            className="h-3.5 w-3.5 accent-sky-600"
            aria-label="Chọn tất cả chứng từ"
          />
          CHỨNG TỪ ({documents.length})
        </label>
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
            const dangXem = document.document_id === selectedId;
            return (
              <div
                key={document.document_id}
                className={`flex items-center gap-2 border-l-2 py-2.5 pl-3 pr-4 transition ${
                  dangXem
                    ? "border-sky-500 bg-sky-50"
                    : "border-transparent hover:bg-slate-50"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked.has(document.document_id)}
                  onChange={() => onToggle(document.document_id)}
                  disabled={busy || running}
                  className="h-3.5 w-3.5 shrink-0 accent-sky-600 disabled:opacity-40"
                  aria-label={`Chọn ${document.file_name}`}
                />
                <button
                  onClick={() => onSelect(document)}
                  className={`flex min-w-0 flex-1 items-center gap-2 text-left text-sm ${
                    dangXem ? "text-slate-900" : "text-slate-700"
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
              </div>
            );
          })
        )}
      </div>

      <div className="space-y-2 border-t border-slate-200 p-3">
        <div className="relative flex">
          <button
            onClick={() => onProcess(engine)}
            disabled={khoa}
            title={
              soChon
                ? `Chạy lại ${soChon} chứng từ đã chọn bằng ${engine}`
                : `Xử lý chứng từ chưa chạy bằng ${engine}`
            }
            className="flex flex-1 items-center justify-center gap-1.5 rounded-l-lg bg-sky-600 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
          >
            {running ? (
              <>
                <Loader2 size={16} className="animate-spin" /> Đang chạy…
              </>
            ) : (
              <>
                <Play size={16} />
                {soChon ? `Xử lý ${soChon} chứng từ` : "Xử lý tất cả"}
              </>
            )}
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              setMenuOpen((value) => !value);
            }}
            disabled={khoa}
            aria-label="Chọn engine OCR"
            title={`Engine OCR: ${engine}`}
            className="flex w-9 items-center justify-center rounded-r-lg border-l border-sky-500 bg-sky-600 text-white transition hover:bg-sky-700 disabled:opacity-50"
          >
            <ChevronDown size={15} />
          </button>

          {menuOpen && (
            <div
              onClick={(event) => event.stopPropagation()}
              className="absolute bottom-full right-0 z-20 mb-1 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
            >
              <p className="border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-500">
                ĐỌC CHỮ BẰNG
              </p>
              {OCR_ENGINES.map((lua_chon) => (
                <button
                  key={lua_chon.name}
                  onClick={() => {
                    setEngine(lua_chon.name);
                    setMenuOpen(false);
                  }}
                  className="block w-full px-3 py-2 text-left text-sm transition hover:bg-slate-50"
                >
                  <span className="flex items-center gap-1.5 font-medium text-slate-800">
                    {lua_chon.name}
                    {lua_chon.name === engine && (
                      <Check size={13} className="text-sky-600" />
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-500">
                    {lua_chon.label}
                  </span>
                  {/* Cảnh báo đặt NGAY chỗ chọn, không chôn trong tài liệu: đo
                      trên hoá đơn thật thì Textract mất gần hết dấu tiếng Việt,
                      dù số vẫn đọc đúng. */}
                  {!lua_chon.supportsVietnamese && (
                    <span className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                      <AlertTriangle size={11} /> không hỗ trợ tiếng Việt
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Đối chiếu KHÔNG gọi AI nên bấm thoải mái. Để cạnh nút Xử lý để thấy
            rõ đây là hai việc khác nhau, không phải hai bước của một việc. */}
        <button
          onClick={onReconcile}
          disabled={busy || running || !canReconcile}
          title="So các chứng từ đã xử lý với nhau. Không gọi AI, không tốn tiền."
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
        >
          <RotateCw size={14} /> Đối chiếu lại
        </button>

        <p className="text-center text-xs text-slate-400">
          {soChon
            ? `${soChon} đã chọn · chạy lại kể cả đã xong`
            : "không chọn = chỉ chạy cái chưa xong"}
        </p>
      </div>
    </aside>
  );
}
