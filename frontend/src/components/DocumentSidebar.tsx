import { useRef } from "react";
import type { DocumentView } from "../types";

/** Sidebar CHỈ có danh sách file và nút Xử lý.
 *
 *  Không đặt thanh tiến độ hay thông báo trạng thái ở đây — mọi thứ thể hiện
 *  quá trình xử lý đều nằm ở khung phải. Mỗi dòng chỉ có icon + tên file.
 */

function icon(document: DocumentView) {
  if (document.status === "FAILED") return { glyph: "✕", className: "text-red-600" };
  if (document.status === "VALIDATED") return { glyph: "✓", className: "text-emerald-600" };
  if (document.status === "PENDING") return { glyph: "○", className: "text-slate-400" };
  return { glyph: "⟳", className: "animate-spin text-sky-600" };
}

interface Props {
  projectName: string;
  documents: DocumentView[];
  selectedId: string | null;
  running: boolean;
  busy: boolean;
  onSelect: (document: DocumentView) => void;
  onUpload: (files: FileList) => void;
  onProcess: () => void;
}

export function DocumentSidebar({
  projectName,
  documents,
  selectedId,
  running,
  busy,
  onSelect,
  onUpload,
  onProcess,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <a href="/" className="text-sm text-sky-700 hover:underline">
          ← Danh sách project
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
          className="flex h-6 w-6 items-center justify-center rounded border border-slate-300 text-base leading-none text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          +
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {documents.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-slate-500">
            Chưa có chứng từ.
            <br />
            Bấm <span className="font-medium">+</span> để tải lên.
          </p>
        ) : (
          documents.map((document) => {
            const { glyph, className } = icon(document);
            const selected = document.document_id === selectedId;
            return (
              <button
                key={document.document_id}
                onClick={() => onSelect(document)}
                className={`flex w-full items-center gap-2 border-l-2 px-4 py-2.5 text-left text-sm transition ${
                  selected
                    ? "border-sky-500 bg-sky-50 text-slate-900"
                    : "border-transparent text-slate-700 hover:bg-slate-50"
                }`}
              >
                <span className={`w-4 shrink-0 text-center ${className}`}>{glyph}</span>
                <span className="truncate" title={document.file_name}>
                  {document.file_name}
                </span>
              </button>
            );
          })
        )}
      </div>

      <div className="border-t border-slate-200 p-3">
        <button
          onClick={onProcess}
          disabled={busy || running || documents.length === 0}
          className="w-full rounded-lg bg-sky-600 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
        >
          {running ? "Đang chạy…" : "▶ Xử lý"}
        </button>
      </div>
    </aside>
  );
}
