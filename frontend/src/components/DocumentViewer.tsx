import { ExternalLink, PanelLeftClose } from "lucide-react";
import { useEffect, useState } from "react";
import type { DocumentView } from "../types";

const IMAGE_TYPES = new Set(["png", "jpg", "jpeg", "tiff"]);

// view_url là presigned URL, server ký lại ở mỗi lần GET /projects/{id}
// (hạn 3600 giây). Bấm Lưu ở tab Sửa gây refresh() → URL đổi → src của
// iframe đổi → PDF tải lại và nhảy về trang 1. Giữ URL cũ theo document_id
// trong gần hết vòng đời của nó để đặt cạnh tab Sửa không bị nhảy trang.
const HAN_GIU_MS = 50 * 60 * 1000; // URL sống 60 phút; đổi sớm 10 phút cho chắc
const urlDaGiu = new Map<string, { url: string; luc: number }>();

function urlOnDinh(documentId: string, url: string): string {
  const cu = urlDaGiu.get(documentId);
  const bayGio = Date.now();
  if (cu && bayGio - cu.luc < HAN_GIU_MS) return cu.url;
  urlDaGiu.set(documentId, { url, luc: bayGio });
  return url;
}

/** Xem file gốc bằng view_url (presigned GET) API đã trả sẵn.
 *  PDF nhúng iframe cho trình duyệt tự render; ảnh thì dùng thẻ img.
 */
export function DocumentViewer({
  document,
  onCollapse,
}: {
  document: DocumentView | null;
  onCollapse?: () => void;
}) {
  const [phong, setPhong] = useState(false);

  // Đổi chứng từ thì thu ảnh về cỡ vừa khung, cho đỡ giật bố cục.
  useEffect(() => {
    setPhong(false);
  }, [document?.document_id]);

  const url = document?.view_url ? urlOnDinh(document.document_id, document.view_url) : "";
  const laAnh = IMAGE_TYPES.has((document?.file_type ?? "").toLowerCase());

  return (
    <div className="flex h-full flex-col border-r border-slate-200 bg-white">
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-200 px-3 py-2.5 text-sm">
        {onCollapse && (
          <button
            onClick={onCollapse}
            title="Ẩn chứng từ gốc"
            aria-label="Ẩn chứng từ gốc"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <PanelLeftClose size={16} />
          </button>
        )}
        <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
          {document ? document.file_name : "Chứng từ gốc"}
        </span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="flex shrink-0 items-center gap-1 text-sky-700 hover:underline"
          >
            Mở tab mới <ExternalLink size={13} />
          </a>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-slate-100 p-2">
        {!document ? (
          <p className="py-20 text-center text-slate-500">
            Chọn một chứng từ ở danh sách bên trái để xem.
          </p>
        ) : !url ? (
          <p className="py-20 text-center text-slate-500">
            Chưa có file để xem — có thể chưa tải lên xong.
          </p>
        ) : laAnh ? (
          <img
            key={document.document_id}
            src={url}
            alt={document.file_name}
            onClick={() => setPhong((truoc) => !truoc)}
            className={`mx-auto rounded shadow ${
              phong ? "max-w-none cursor-zoom-out" : "max-w-full cursor-zoom-in"
            }`}
          />
        ) : (
          <iframe
            key={document.document_id}
            src={url}
            title={document.file_name}
            className="h-full w-full rounded border border-slate-300 bg-white"
          />
        )}
      </div>
    </div>
  );
}
