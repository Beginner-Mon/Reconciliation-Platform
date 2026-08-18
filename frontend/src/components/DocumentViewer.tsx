import type { DocumentView } from "../types";

const IMAGE_TYPES = new Set(["png", "jpg", "jpeg", "tiff"]);

/** Xem file gốc bằng view_url (presigned GET) API đã trả sẵn.
 *  PDF nhúng iframe cho trình duyệt tự render; ảnh thì dùng thẻ img.
 */
export function DocumentViewer({ document }: { document: DocumentView | null }) {
  if (!document) {
    return (
      <p className="py-20 text-center text-slate-500">
        Chọn một chứng từ ở danh sách bên trái để xem.
      </p>
    );
  }

  if (!document.view_url) {
    return (
      <p className="py-20 text-center text-slate-500">
        Chưa có file để xem — có thể chưa tải lên xong.
      </p>
    );
  }

  const isImage = IMAGE_TYPES.has((document.file_type ?? "").toLowerCase());

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 text-sm">
        <span className="truncate font-medium text-slate-700">{document.file_name}</span>
        <a
          href={document.view_url}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-sky-700 hover:underline"
        >
          Mở tab mới ↗
        </a>
      </div>

      <div className="flex-1 overflow-auto bg-slate-100 p-4">
        {isImage ? (
          <img
            src={document.view_url}
            alt={document.file_name}
            className="mx-auto max-w-full rounded shadow"
          />
        ) : (
          <iframe
            src={document.view_url}
            title={document.file_name}
            className="h-full min-h-[32rem] w-full rounded border border-slate-300 bg-white"
          />
        )}
      </div>
    </div>
  );
}
