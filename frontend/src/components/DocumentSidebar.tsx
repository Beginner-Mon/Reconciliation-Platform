import {
  AlertTriangle,
  Anchor,
  ArrowLeft,
  Check,
  ChevronDown,
  Loader2,
  Play,
  Plus,
  RotateCw,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AnchorInfo } from "../anchor";
import { DEFAULT_OCR_ENGINE, OCR_ENGINES } from "../format";
import type { DocumentStatus, DocumentView } from "../types";

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

/** Tag trạng thái thay cho dấu ✓/✗/○ — biểu tượng trơn khó hiểu.
 *  Giữ đúng mã tiếng Anh vì nó trùng với API, audit và tài liệu (dễ đối chiếu
 *  khi debug); nghĩa tiếng Việt nằm ở tooltip.
 *  `Record<DocumentStatus, …>` bắt buộc khai đủ mọi trạng thái — thêm trạng
 *  thái mới ở types.ts mà quên chỗ này thì typecheck đỏ. */
const TAG: Record<DocumentStatus, { nghia: string; mau: string; dangChay?: boolean }> = {
  PENDING: { nghia: "Mới tải lên, chưa xử lý", mau: "border-slate-200 bg-slate-50 text-slate-500" },
  PROCESSING: { nghia: "Đang xử lý", mau: "border-sky-200 bg-sky-50 text-sky-700", dangChay: true },
  OCR_DONE: { nghia: "Đã đọc chữ, chờ trích xuất", mau: "border-sky-200 bg-sky-50 text-sky-700", dangChay: true },
  EXTRACTED: { nghia: "Đã trích xuất, chờ kiểm tra", mau: "border-sky-200 bg-sky-50 text-sky-700", dangChay: true },
  VALIDATED: { nghia: "Đã xử lý xong và qua kiểm tra", mau: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  FAILED: { nghia: "Lỗi ở một bước — xem tab Trích xuất", mau: "border-red-200 bg-red-50 text-red-700" },
};

function StatusTag({ document }: { document: DocumentView }) {
  const tag = TAG[document.status];
  // FAILED: tooltip hiện đúng lý do lỗi, không chỉ câu chung chung.
  const tooltip = document.status === "FAILED" && document.error ? document.error : tag.nghia;
  return (
    <span
      title={tooltip}
      className={`inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-px text-[10px] font-semibold tracking-wide ${tag.mau}`}
    >
      {tag.dangChay && <Loader2 size={10} className="animate-spin" />}
      {document.status}
    </span>
  );
}

interface Props {
  projectName: string;
  documents: DocumentView[];
  selectedId: string | null;
  checkedIds: string[];
  running: boolean;
  stopping: boolean;
  busy: boolean;
  canReconcile: boolean;
  reconcileStale: boolean;
  onSelect: (document: DocumentView) => void;
  onToggle: (documentId: string) => void;
  onToggleAll: () => void;
  onUpload: (files: FileList) => void;
  onProcess: (engine: string) => void;
  onStop: () => void;
  onReconcile: () => void;
  onDelete: (document: DocumentView) => void;
  anchors: Map<string, AnchorInfo>;
  onSetAnchor: (document: DocumentView) => void;
}

export function DocumentSidebar({
  projectName,
  documents,
  selectedId,
  checkedIds,
  running,
  stopping,
  busy,
  canReconcile,
  reconcileStale,
  onSelect,
  onToggle,
  onToggleAll,
  onUpload,
  onProcess,
  onStop,
  onReconcile,
  onDelete,
  anchors,
  onSetAnchor,
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
            const goc = anchors.get(document.document_id);
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
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={document.file_name}>
                      {document.file_name}
                    </span>
                    <span className="mt-1 flex min-w-0 items-center gap-1.5">
                      <StatusTag document={document} />
                      {document.needs_confirmation && (
                        <span
                          title="Có cảnh báo cần sửa hoặc tắt trước khi duyệt"
                          className="shrink-0 rounded border border-amber-300 bg-amber-50 px-1.5 py-px text-[10px] font-semibold tracking-wide text-amber-800"
                        >
                          CẦN XEM
                        </span>
                      )}
                      {goc?.isAnchor && (
                        <span
                          title={
                            goc.chosenByUser
                              ? "Chứng từ gốc do người dùng chọn: chứng từ còn lại trong nhóm được so với chứng từ này"
                              : "Chứng từ gốc do hệ thống tự chọn theo vai trò: chứng từ còn lại trong nhóm được so với chứng từ này"
                          }
                          className="shrink-0 rounded border border-indigo-300 bg-indigo-50 px-1.5 py-px text-[10px] font-semibold tracking-wide text-indigo-700"
                        >
                          GỐC
                        </span>
                      )}
                      {document.ocr_engine && (
                        <span className="truncate text-xs text-slate-400">
                          {document.ocr_engine}
                        </span>
                      )}
                    </span>
                  </span>
                </button>
                {goc && (
                  <button
                    onClick={() => onSetAnchor(document)}
                    disabled={busy || running || goc.isAnchor}
                    title={
                      goc.isAnchor
                        ? "Đang là chứng từ gốc của nhóm"
                        : "Đặt làm chứng từ gốc: đối chiếu lại ngay, không gọi AI"
                    }
                    aria-label={
                      goc.isAnchor
                        ? `${document.file_name} đang là chứng từ gốc`
                        : `Đặt ${document.file_name} làm chứng từ gốc`
                    }
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded ${
                      goc.isAnchor
                        ? "text-indigo-600"
                        : "text-slate-400 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-40"
                    }`}
                  >
                    <Anchor size={14} />
                  </button>
                )}
                <button
                  onClick={() => onDelete(document)}
                  disabled={busy || running}
                  title={`Xoá ${document.file_name}`}
                  aria-label={`Xoá ${document.file_name}`}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                >
                  <Trash2 size={14} />
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
                <Loader2 size={16} className="animate-spin" />{" "}
                {stopping ? "Đang dừng…" : "Đang chạy…"}
              </>
            ) : (
              <>
                <Play size={16} />
                {soChon ? `Xử lý ${soChon} chứng từ` : "Xử lý tất cả"}
              </>
            )}
          </button>
          {running ? (
            <button
              onClick={onStop}
              disabled={busy}
              aria-label="Dừng run đang chạy"
              title={
                stopping
                  ? "Đang dừng — bấm lại để kiểm tra run còn chạy không"
                  : "Dừng: không gọi AI thêm cho các chứng từ còn lại"
              }
              className="flex w-9 items-center justify-center rounded-r-lg border-l border-red-500 bg-red-600 text-white transition hover:bg-red-700 disabled:opacity-50"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
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
          )}

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
          title={
            reconcileStale
              ? "Có chứng từ sửa sau lần đối chiếu trước — chạy lại để duyệt được"
              : "So các chứng từ đã xử lý với nhau. Không gọi AI, không tốn tiền."
          }
          className={`flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition disabled:opacity-50 ${
            reconcileStale
              ? "border-amber-400 bg-amber-50 font-medium text-amber-900 hover:bg-amber-100"
              : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
          }`}
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
