import { ExternalLink, Minus, PanelLeftClose, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Review } from "../hooks/useReview";
import type { DocumentView } from "../types";
import { PageOverlay } from "./PageOverlay";
import { PdfPages } from "./PdfPages";

const IMAGE_TYPES = new Set(["png", "jpg", "jpeg", "tiff"]);
const MUC_PHONG = [1, 1.5, 2, 3];

// view_url là presigned URL, server ký lại ở mỗi lần GET /projects/{id}
// (hạn 3600 giây). Bấm Lưu gây refresh() → URL đổi → PDF tải lại và nhảy về
// trang 1. Giữ URL cũ theo document_id trong gần hết vòng đời của nó.
const HAN_GIU_MS = 50 * 60 * 1000; // URL sống 60 phút; đổi sớm 10 phút cho chắc
const urlDaGiu = new Map<string, { url: string; luc: number }>();

function urlOnDinh(documentId: string, url: string): string {
  const cu = urlDaGiu.get(documentId);
  const bayGio = Date.now();
  if (cu && bayGio - cu.luc < HAN_GIU_MS) return cu.url;
  urlDaGiu.set(documentId, { url, luc: bayGio });
  return url;
}

const NUT_PHONG =
  "flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40";

export function DocumentViewer({
  document,
  onCollapse,
  review,
}: {
  document: DocumentView | null;
  onCollapse?: () => void;
  review?: Review | null;
}) {
  const [phong, setPhong] = useState(0);
  const [hienKhung, setHienKhung] = useState(true);
  const vung = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setPhong(0);
  }, [document?.document_id]);

  const nhay = review?.nhay ?? 0;
  useEffect(() => {
    const dau = review?.tieuDiem[0];
    if (!dau || !vung.current) return;
    vung.current
      .querySelector(`rect[data-ref="${dau[0]}:${dau[1]}"]`)
      ?.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
  }, [nhay]);

  const url = document?.view_url ? urlOnDinh(document.document_id, document.view_url) : "";
  const laAnh = IMAGE_TYPES.has((document?.file_type ?? "").toLowerCase());
  const pages = review?.ocr?.pages ?? [];
  const coKhung = pages.some((page) => (page.words ?? []).length > 0);
  const rong = `${MUC_PHONG[phong] * 100}%`;

  const lop = (page: number) => {
    const words = pages[page]?.words;
    if (!review || !hienKhung || !words) return null;
    return <PageOverlay page={page} words={words} review={review} />;
  };

  return (
    <div className="flex h-full flex-col border-r border-slate-200 bg-white">
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-200 px-3 py-2.5 text-sm">
        {onCollapse && (
          <button
            onClick={onCollapse}
            title="Ẩn file gốc"
            aria-label="Ẩn file gốc"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <PanelLeftClose size={16} />
          </button>
        )}
        <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
          {document ? document.file_name : "File gốc"}
        </span>
        {review && coKhung && (
          <label className="flex shrink-0 items-center gap-1 text-slate-600">
            <input
              type="checkbox"
              checked={hienKhung}
              onChange={(event) => setHienKhung(event.target.checked)}
            />
            Khung OCR
          </label>
        )}
        {url && (
          <span className="flex shrink-0 items-center">
            <button
              onClick={() => setPhong((cu) => Math.max(cu - 1, 0))}
              disabled={phong === 0}
              title="Thu nhỏ"
              aria-label="Thu nhỏ"
              className={NUT_PHONG}
            >
              <Minus size={14} />
            </button>
            <button
              onClick={() => setPhong((cu) => Math.min(cu + 1, MUC_PHONG.length - 1))}
              disabled={phong === MUC_PHONG.length - 1}
              title="Phóng to"
              aria-label="Phóng to"
              className={NUT_PHONG}
            >
              <Plus size={14} />
            </button>
          </span>
        )}
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

      {review && review.ocr && !review.dangTai && !coKhung && (
        <p className="shrink-0 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
          Chứng từ này chưa có vị trí chữ nên không hiện được khung. Tích chọn nó rồi bấm Xử lý để
          chạy lại.
        </p>
      )}

      <div ref={vung} className="min-h-0 flex-1 overflow-auto bg-slate-100 p-2">
        {!document ? (
          <p className="py-20 text-center text-slate-500">
            Chọn một chứng từ ở danh sách bên trái để xem.
          </p>
        ) : !url ? (
          <p className="py-20 text-center text-slate-500">
            Chưa có file để xem — có thể chưa tải lên xong.
          </p>
        ) : laAnh ? (
          <div className="relative mx-auto" style={{ width: rong }}>
            <img
              key={document.document_id}
              src={url}
              alt={document.file_name}
              className="block w-full rounded shadow"
            />
            {lop(0)}
          </div>
        ) : (
          <div className="mx-auto" style={{ width: rong }}>
            <PdfPages key={document.document_id} url={url}>
              {lop}
            </PdfPages>
          </div>
        )}
      </div>
    </div>
  );
}
