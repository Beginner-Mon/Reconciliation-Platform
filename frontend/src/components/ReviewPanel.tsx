import { AlertTriangle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { LOW_CONFIDENCE, formatValue } from "../format";
import type { Review } from "../hooks/useReview";
import {
  MAU_COT,
  MAU_TRUONG,
  NHAN_TRUONG,
  SO_NGUYEN,
  VAI_TRO_CHUNG_TU,
  VAI_TRO_COT,
  chuCuaDich,
  chuCuaKhung,
  cungDich,
  dichCuaDoiChieu,
  dichCuaTruong,
  hienGiaTri,
  khungCuaDich,
  laCauTrucCu,
  maDich,
  sapXep,
  type Draft,
  type Target,
} from "../review/draft";
import { docNhap, luuNhap, xoaNhap } from "../review/cache";
import type { ColumnRole, DocumentView } from "../types";
import { OcrText } from "./OcrText";
import { ValidationFlags } from "./ValidationFlags";

const NUT =
  "rounded border border-slate-300 bg-white px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const CHUA_RO = "Chưa rõ vị trí trên chứng từ";

export interface PendingFocus {
  docId: string;
  field: string;
}

function khopHinh(mau: Draft, ban: Draft): boolean {
  if (
    mau.scalars.length !== ban.scalars.length ||
    mau.others.length !== ban.others.length ||
    mau.tables.length !== ban.tables.length
  ) {
    return false;
  }
  for (let t = 0; t < mau.tables.length; t++) {
    if (
      mau.tables[t].columns.length !== ban.tables[t]?.columns.length ||
      mau.tables[t].rows.length !== ban.tables[t]?.rows.length
    ) {
      return false;
    }
  }
  return true;
}

function ONhap({
  ma,
  giaTri,
  mucClass,
  onXong,
  onHuy,
}: {
  ma: string;
  giaTri: string;
  mucClass: string;
  onXong: (chu: string) => void;
  onHuy: () => void;
}) {
  const [chu, setChu] = useState(giaTri);
  return (
    <input
      autoFocus
      data-dich={ma}
      value={chu}
      onChange={(event) => setChu(event.target.value)}
      onBlur={() => onXong(chu)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onXong(chu);
        if (event.key === "Escape") onHuy();
      }}
      className={`${mucClass} rounded border border-sky-500 bg-white outline-none focus:border-sky-600`}
    />
  );
}

function NutSuaInline({ review, dich }: { review: Review; dich: Target }) {
  if (dich.kind !== "cell" || !review.draft || !review.goc) {
    return null;
  }
  const taiCho = sapXep(review.layout?.tables[dich.t]?.at?.[dich.r]?.[dich.c] ?? []);
  const cu = review.goc.tables[dich.t]?.rows[dich.r]?.[dich.c];
  const nay = review.draft.tables[dich.t]?.rows[dich.r]?.[dich.c];
  const canhBao = cu && nay && cu.value === nay.value ? review.co.get(`${dich.t}:${dich.r}:${dich.c}`) : undefined;
  const khac =
    taiCho.length > 0 && JSON.stringify(taiCho) !== JSON.stringify(sapXep(khungCuaDich(review.draft, dich)));
  if (!canhBao && !khac) {
    return null;
  }
  return (
    <div className="mt-1 space-y-1">
      {canhBao && <p className="text-xs text-red-700">{canhBao}</p>}
      {khac && (
        <button
          onClick={review.layTaiCho}
          className="rounded bg-sky-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-sky-700"
        >
          Lấy «{chuCuaKhung(review.pages, taiCho)}» tại vị trí này
        </button>
      )}
    </div>
  );
}

function O({
  review,
  maXem,
  dich,
  className,
  title,
  children,
}: {
  review: Review;
  maXem: string;
  dich: Target;
  className: string;
  title?: string;
  children: ReactNode;
}) {
  const ma = maDich(dich);
  const dangSua = cungDich(review.dich, dich);
  if (dangSua && review.draft) {
    const giaTri = chuCuaDich(review.draft, dich);
    return (
      <div className="min-w-0">
        <ONhap
          key={`${ma}|${giaTri}`}
          ma={ma}
          giaTri={giaTri}
          mucClass={className}
          onXong={review.go}
          onHuy={review.boDich}
        />
        <NutSuaInline review={review} dich={dich} />
      </div>
    );
  }
  const vong = dangSua
    ? "ring-2 ring-inset ring-sky-600"
    : ma === maXem
      ? "ring-2 ring-inset ring-amber-500"
      : "";
  return (
    <button
      type="button"
      data-dich={ma}
      title={title}
      onClick={() => review.chonDich(dich)}
      onMouseEnter={() => review.re(review.draft ? khungCuaDich(review.draft, dich) : [])}
      onMouseLeave={() => review.re([])}
      className={`${className} ${vong}`}
    >
      {children}
    </button>
  );
}

interface KhoiProps {
  review: Review;
  draft: Draft;
  goc: Draft;
  coKhung: boolean;
  maXem: string;
}

function KhoiTruong({
  review,
  draft,
  goc,
  coKhung,
  maXem,
  confidence,
}: KhoiProps & { confidence: Record<string, number> }) {
  const vaiTro = VAI_TRO_CHUNG_TU.some((v) => v.value === draft.role)
    ? VAI_TRO_CHUNG_TU
    : [...VAI_TRO_CHUNG_TU, { value: draft.role, label: draft.role }];

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-700">Trường chính</h3>
        <label className="flex items-center gap-1 text-sm text-slate-600">
          Vai trò chứng từ
          <select
            value={draft.role}
            onChange={(event) => review.datVaiTro(event.target.value)}
            className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-sm"
          >
            {vaiTro.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-1 gap-x-4 gap-y-0.5 @md:grid-cols-2">
        {draft.scalars.map((s, i) => {
          const dich: Target = { kind: "scalar", key: s.key };
          const ma = maDich(dich);
          const dangSua = cungDich(review.dich, dich);
          const conf = confidence[s.key];
          const low = typeof conf === "number" && conf < LOW_CONFIDENCE;
          const cu = goc.scalars[i];
          const doi = !cu || cu.value !== s.value || JSON.stringify(cu.src) !== JSON.stringify(s.src);
          const mo = coKhung && s.value !== "" && s.src.length === 0;
          const hien =
            SO_NGUYEN.has(s.key) && /^-?\d+$/.test(s.value)
              ? hienGiaTri(Number(s.value), review.kieu)
              : s.value;
          const vong = dangSua
            ? "ring-2 ring-inset ring-sky-600"
            : ma === maXem
              ? "ring-2 ring-inset ring-amber-500"
              : "";
          return (
            <div
              key={s.key}
              className={`flex items-baseline gap-2 rounded px-2 py-1 text-sm hover:bg-slate-100 ${
                doi ? "bg-emerald-50" : ""
              } ${vong}`}
            >
              <button
                type="button"
                onClick={() => review.chonDich(dich)}
                onMouseEnter={() => review.re(review.draft ? khungCuaDich(review.draft, dich) : [])}
                onMouseLeave={() => review.re([])}
                className="w-32 shrink-0 text-left text-slate-500"
              >
                {NHAN_TRUONG[s.key] ?? s.key}
              </button>
              <span
                className="h-2.5 w-2.5 shrink-0 self-center rounded-sm border border-slate-300"
                style={{ background: s.src.length > 0 ? MAU_TRUONG : "transparent" }}
              />
              {dangSua && review.draft ? (
                <div className="min-w-0 flex-1">
                  <ONhap
                    key={`${ma}|${chuCuaDich(review.draft, dich)}`}
                    ma={ma}
                    giaTri={chuCuaDich(review.draft, dich)}
                    mucClass="min-w-0 flex-1 px-1 py-0.5 text-sm text-slate-900"
                    onXong={review.go}
                    onHuy={review.boDich}
                  />
                  <NutSuaInline review={review} dich={dich} />
                </div>
              ) : (
                <button
                  type="button"
                  data-dich={ma}
                  title={mo ? CHUA_RO : undefined}
                  onClick={() => review.chonDich(dich)}
                  onMouseEnter={() => review.re(review.draft ? khungCuaDich(review.draft, dich) : [])}
                  onMouseLeave={() => review.re([])}
                  className="min-w-0 flex-1 break-words text-left"
                >
                  <span className={`${low ? "text-amber-900" : "text-slate-900"} ${mo ? "italic" : ""}`}>
                    {hien || "—"}
                  </span>
                  {low && (
                    <span
                      className="inline-flex shrink-0 items-center gap-0.5 text-xs text-amber-600"
                      title={`AI đọc trường này với độ tin cậy ${conf.toFixed(2)} — nên kiểm lại`}
                    >
                      <AlertTriangle size={11} /> {conf.toFixed(2)}
                    </span>
                  )}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function KhoiTruongBoSung({ review, draft, coKhung, maXem }: KhoiProps) {
  return (
    <section>
      <h3 className="mb-2 font-semibold text-slate-700">Trường bổ sung theo chứng từ</h3>
      <div className="space-y-0.5">
        {draft.others.map((o, i) => {
          const mo = coKhung && o.value !== "" && o.src.length === 0;
          return (
            <div key={i} className="flex items-start gap-1 text-sm">
              <O
                review={review}
                maXem={maXem}
                dich={{ kind: "other", i, part: "name" }}
                className="w-2/5 shrink-0 break-words rounded px-2 py-1 text-left text-slate-500 hover:bg-slate-100"
              >
                {o.name || "(chưa đặt tên)"}
              </O>
              <O
                review={review}
                maXem={maXem}
                dich={{ kind: "other", i, part: "value" }}
                title={mo ? CHUA_RO : undefined}
                className={`min-w-0 flex-1 whitespace-pre-wrap break-words rounded px-2 py-1 text-left text-slate-900 hover:bg-slate-100 ${
                  mo ? "italic" : ""
                }`}
              >
                {o.value || "—"}
              </O>
              <button
                onClick={() => review.xoaTruong(i)}
                title="Bỏ trường này"
                aria-label={`Bỏ trường ${o.name}`}
                className="mt-1 shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </div>
      <button onClick={review.themTruong} className="mt-1 text-sm text-sky-700 hover:underline">
        + Thêm trường
      </button>
    </section>
  );
}

function KhoiBang({ review, draft, goc, coKhung, maXem }: KhoiProps) {
  return (
    <>
      {draft.tables.map((table, t) => (
        <section key={t}>
          <h3 className="mb-1 font-semibold text-slate-700">Bảng {t + 1}</h3>
          <div className="overflow-auto">
            <table className="border-collapse text-sm">
              <thead>
                <tr>
                  <th className="border border-slate-300 bg-white px-1 text-xs font-normal text-slate-400">
                    #
                  </th>
                  {table.columns.map((column, c) => (
                    <th
                      key={c}
                      className="min-w-24 border border-slate-300 p-0 text-left align-bottom"
                      style={{ background: MAU_COT[c % MAU_COT.length] }}
                    >
                      <O
                        review={review}
                        maXem={maXem}
                        dich={{ kind: "header", t, c }}
                        className="block w-full px-2 py-1 text-left font-semibold"
                      >
                        {column.header || "(trống)"}
                      </O>
                      <select
                        aria-label={`Bảng ${t + 1}, vai trò của cột ${column.header}`}
                        value={column.role ?? ""}
                        onChange={(event) =>
                          review.datVaiTroCot(t, c, (event.target.value || null) as ColumnRole | null)
                        }
                        className="block w-full border-t border-slate-300 bg-white/70 px-1 py-0.5 text-xs font-normal text-slate-700"
                      >
                        <option value="">không đối chiếu</option>
                        {VAI_TRO_COT.map((v) => (
                          <option key={v.value} value={v.value}>
                            {v.label}
                          </option>
                        ))}
                      </select>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, r) => (
                  <tr key={r} className={table.moi[r] ? "bg-emerald-50" : "bg-white"}>
                    <th className="border border-slate-300 px-1 text-xs font-normal text-slate-400">
                      {r + 1}
                    </th>
                    {row.map((cell, c) => {
                      const cu = goc.tables[t]?.rows[r]?.[c];
                      const doi =
                        cu !== undefined &&
                        (cu.value !== cell.value || JSON.stringify(cu.src) !== JSON.stringify(cell.src));
                      const co =
                        cu !== undefined && cu.value === cell.value
                          ? review.co.get(`${t}:${r}:${c}`)
                          : undefined;
                      const mo =
                        coKhung && cell.value !== null && cell.value !== "" && cell.src.length === 0;
                      return (
                        <td key={c} className="border border-slate-300 p-0">
                          <O
                            review={review}
                            maXem={maXem}
                            dich={{ kind: "cell", t, r, c }}
                            title={co ?? (mo ? CHUA_RO : undefined)}
                            className={`block w-full whitespace-nowrap px-2 py-1 text-left ${
                              co ? "bg-red-100 font-semibold text-red-800" : ""
                            } ${doi ? "outline-2 -outline-offset-2 outline-emerald-600" : ""} ${
                              mo && !co ? "italic text-slate-500" : ""
                            }`}
                          >
                            {hienGiaTri(cell.value, review.kieu) || "·"}
                          </O>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-1 flex gap-4 text-sm">
            <button onClick={() => review.themDong(t)} className="text-sky-700 hover:underline">
              + Thêm dòng
            </button>
            {table.rows.length > 0 && (
              <button
                onClick={() => {
                  const cuoi = table.rows.length - 1;
                  if (table.moi[cuoi] || window.confirm(`Xoá dòng ${cuoi + 1} của bảng ${t + 1}?`)) {
                    review.xoaDongCuoi(t);
                  }
                }}
                className="text-slate-500 hover:text-red-600 hover:underline"
              >
                Xoá dòng cuối
              </button>
            )}
          </div>
        </section>
      ))}
    </>
  );
}

export function ReviewPanel({
  document,
  review,
  pendingFocus,
  onFocusDone,
}: {
  document: DocumentView | null;
  review: Review;
  pendingFocus?: PendingFocus | null;
  onFocusDone?: () => void;
}) {
  const vung = useRef<HTMLDivElement>(null);
  const nhanXem = review.xem ? review.nhan.get(review.xem[0] + ":" + review.xem[1]) : undefined;
  const maXem = nhanXem ? maDich(nhanXem.dich) : "";
  const [khoiPhuc, setKhoiPhuc] = useState<Draft | null>(null);

  useEffect(() => {
    if (!maXem || !vung.current) return;
    vung.current
      .querySelector(`[data-dich="${maXem}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [maXem]);

  useEffect(() => {
    if (!review.dich) return;
    const dong = (event: MouseEvent) => {
      const muc = event.target as Element | null;
      if (muc?.closest?.("input,select,textarea,button,a,[data-dich],rect[data-ref]")) return;
      review.boDich();
    };
    window.document.addEventListener("click", dong);
    return () => window.document.removeEventListener("click", dong);
  }, [Boolean(review.dich)]);

  useEffect(() => {
    if (!pendingFocus || !document || pendingFocus.docId !== document.document_id) return;
    if (!review.draft) return;
    const { dich } = dichCuaDoiChieu(pendingFocus.field, document.extraction ?? {});
    if (dich) review.moDich(dich);
    onFocusDone?.();
  }, [pendingFocus?.docId, pendingFocus?.field, document?.document_id, Boolean(review.draft)]);

  useEffect(() => {
    if (!document || !review.draft || !review.goc) {
      setKhoiPhuc(null);
      return;
    }
    if (JSON.stringify(review.draft) !== JSON.stringify(review.goc)) {
      setKhoiPhuc(null);
      luuNhap(document.project_id, document.document_id, document.updated_at ?? null, review.draft);
      return;
    }
    const base = document.updated_at ?? null;
    const ban = docNhap(document.project_id, document.document_id, base);
    if (!ban || !khopHinh(review.goc, ban) || JSON.stringify(ban) === JSON.stringify(review.goc)) {
      if (ban) xoaNhap(document.project_id, document.document_id);
      setKhoiPhuc(null);
      return;
    }
    setKhoiPhuc(ban);
  }, [document?.document_id, document?.updated_at, Boolean(review.draft), Boolean(review.goc), review.coThayDoi]);

  if (!document) {
    return <p className="py-20 text-center text-slate-500">Chọn một chứng từ bên trái.</p>;
  }

  const extraction = document.extraction;
  const { draft, goc } = review;
  const coKhung = review.pages.some((page) => (page.words ?? []).length > 0);
  const loiKiemTra =
    document.validation && !document.validation.valid
      ? [...document.validation.schema_errors, ...document.validation.rule_errors].join("; ")
      : "";

  return (
    <div ref={vung} className="space-y-5 p-6">
      <ValidationFlags
        validation={document.validation}
        nhan={(field) => dichCuaTruong(field, extraction ?? {}).nhan}
        coTheBam={(field) => Boolean(draft) && dichCuaTruong(field, extraction ?? {}).dich !== null}
        choLuu={(field) => {
          const { dich } = dichCuaTruong(field, extraction ?? {});
          return Boolean(dich && draft && goc && chuCuaDich(draft, dich) !== chuCuaDich(goc, dich));
        }}
        onPick={(field) => {
          const { dich } = dichCuaTruong(field, extraction ?? {});
          if (dich) review.moDich(dich);
        }}
        dismissed={document.dismissed_flags}
        onDismiss={(code, field) => review.tatCo(code, field)}
        onReopen={(code, field) => review.moLaiCo(code, field)}
      />

      {khoiPhuc && (
        <p className="rounded border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900">
          Còn bản sửa chưa lưu trong trình duyệt này (giữ 90 phút).{" "}
          <button
            onClick={() => {
              review.nhapTuCache(khoiPhuc);
              setKhoiPhuc(null);
            }}
            className="font-medium text-sky-700 hover:underline"
          >
            Khôi phục
          </button>{" "}
          <button
            onClick={() => {
              xoaNhap(document.project_id, document.document_id);
              setKhoiPhuc(null);
            }}
            className="text-slate-500 hover:underline"
          >
            Bỏ
          </button>
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="min-w-0 truncate font-semibold text-slate-700">{document.file_name}</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {extraction?.document_type && (
            <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">
              Loại: {String(extraction.document_type)}
            </span>
          )}
          {document.ocr_engine && (
            <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">
              OCR: {document.ocr_engine}
            </span>
          )}
          {(document.edited_fields?.length ?? 0) > 0 && (
            <span className="rounded bg-violet-100 px-2 py-0.5 text-violet-700">
              <Pencil size={11} className="inline" /> đã sửa: {document.edited_fields?.join(", ")}
            </span>
          )}
        </div>
      </div>

      {document.status === "FAILED" && document.error ? (
        <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {document.error}
        </p>
      ) : loiKiemTra ? (
        <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          Dữ liệu hiện chưa hợp lệ: {loiKiemTra}
        </p>
      ) : null}

      {!extraction ? (
        <p className="rounded border border-slate-200 bg-white px-3 py-6 text-center text-slate-500">
          Chưa có dữ liệu trích xuất.
        </p>
      ) : !draft || !goc ? (
        <p className="py-10 text-center text-slate-500">Đang tải vị trí chữ…</p>
      ) : (
        <>
          <p className="text-xs text-slate-600">
            Bấm một ô để sửa ngay trong ô đó. Bấm một khung có màu trên chứng từ để xem nó thuộc ô nào. Bấm “+ Thêm trường”
            rồi bấm các khung để đưa chữ vào trường mới.
          </p>

          <KhoiTruong
            review={review}
            draft={draft}
            goc={goc}
            coKhung={coKhung}
            maXem={maXem}
            confidence={document.confidence ?? {}}
          />
          <KhoiTruongBoSung review={review} draft={draft} goc={goc} coKhung={coKhung} maXem={maXem} />

          {draft.khoaBang ? (
            <section>
              <p className="mb-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Bảng trong kết quả trích xuất có cấu trúc không hợp lệ nên không sửa được ở đây. Tích
                chọn chứng từ rồi bấm Xử lý để chạy lại.
              </p>
              <pre className="max-h-72 overflow-auto rounded border border-slate-200 bg-white p-3 text-xs text-slate-700">
                {JSON.stringify(extraction.tables, null, 2)}
              </pre>
            </section>
          ) : (
            <KhoiBang review={review} draft={draft} goc={goc} coKhung={coKhung} maXem={maXem} />
          )}

          {laCauTrucCu(extraction) && (extraction.items ?? []).length > 0 && (
            <section>
              <p className="mb-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Chứng từ này trích xuất theo cấu trúc cũ nên bảng mặt hàng chỉ xem được. Tích chọn nó
                rồi bấm Xử lý để chạy lại và sửa bằng giao diện mới.
              </p>
              <table className="w-full overflow-hidden rounded border border-slate-200 bg-white text-sm">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">Mặt hàng</th>
                    <th className="w-20 px-3 py-1.5 text-right font-medium">SL</th>
                    <th className="w-32 px-3 py-1.5 text-right font-medium">Đơn giá</th>
                  </tr>
                </thead>
                <tbody>
                  {(extraction.items ?? []).map((item, index) => (
                    <tr key={index} className="border-t border-slate-100">
                      <td className="px-3 py-1.5 text-slate-900">{item.item_name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{item.quantity}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {item.unit_price == null ? "—" : formatValue(item.unit_price)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {review.error && (
            <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              {review.error}
            </p>
          )}
          {review.saved && !review.error && (
            <p className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Đã lưu. Nếu có đổi dữ liệu thì kết quả đối soát cũ đã lỗi thời — bấm Đối chiếu lại ở bên
              trái.
            </p>
          )}

          <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 py-3">
            <span className="text-sm text-slate-500">
              {review.coThayDoi ? "Có thay đổi chưa lưu." : "Chưa có thay đổi."}
            </span>
            <div className="flex gap-2">
              <button
                onClick={review.hoanTac}
                disabled={!review.coThayDoi || review.saving}
                className={NUT}
              >
                Bỏ thay đổi
              </button>
              <button
                onClick={review.luu}
                disabled={!review.coThayDoi || review.saving}
                className="rounded bg-sky-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
              >
                {review.saving ? "Đang lưu…" : "Lưu"}
              </button>
            </div>
          </div>
        </>
      )}

      <OcrText ocr={review.ocr} loading={review.dangTai} error={review.loiOcr} />
    </div>
  );
}
