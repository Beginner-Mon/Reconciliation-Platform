import type {
  CellValue,
  ColumnRole,
  DocumentRole,
  Extraction,
  OcrLayout,
  OcrResult,
  Sources,
  Table,
  Validation,
  WordRef,
} from "../types";

export type KieuSo = OcrLayout["number_style"];

export interface DraftCell {
  value: CellValue;
  src: WordRef[];
}

export interface DraftColumn {
  header: string;
  role: ColumnRole | null;
  src: WordRef[];
}

export interface DraftTable {
  columns: DraftColumn[];
  rows: DraftCell[][];
  extra: Record<string, CellValue>[];
  moi: boolean[];
}

export interface DraftScalar {
  key: string;
  value: string;
  src: WordRef[];
}

export interface DraftOther {
  name: string;
  value: string;
  nameSrc: WordRef[];
  src: WordRef[];
}

export interface Draft {
  role: string;
  scalars: DraftScalar[];
  others: DraftOther[];
  tables: DraftTable[];
  khoaBang: boolean;
}

export type Target =
  | { kind: "cell"; t: number; r: number; c: number }
  | { kind: "header"; t: number; c: number }
  | { kind: "scalar"; key: string }
  | { kind: "other"; i: number; part: "name" | "value" };

export interface NhanKhung {
  loai: "o" | "tieu-de" | "truong" | "ten-truong" | "lech";
  mau: string;
  chu: string;
  dich: Target;
}

export interface KhungLech {
  refs: WordRef[];
  chu: string;
  dich: Target;
}

export const TRUONG_CHINH = [
  "doc_number",
  "doc_date",
  "order_reference",
  "seller",
  "seller_tax_code",
  "buyer",
  "buyer_tax_code",
  "currency",
  "subtotal",
  "discount_amount",
  "tax_amount",
  "total_amount",
];

export const SO_NGUYEN = new Set(["subtotal", "discount_amount", "tax_amount", "total_amount"]);

export const NHAN_TRUONG: Record<string, string> = {
  doc_number: "Số chứng từ",
  doc_date: "Ngày chứng từ",
  order_reference: "Số tham chiếu (PO)",
  seller: "Bên bán",
  seller_tax_code: "MST bên bán",
  buyer: "Bên mua",
  buyer_tax_code: "MST bên mua",
  currency: "Tiền tệ",
  subtotal: "Tiền trước thuế",
  discount_amount: "Chiết khấu",
  tax_amount: "Tiền thuế",
  total_amount: "Tổng thanh toán",
};

export const VAI_TRO_COT: { value: ColumnRole; label: string }[] = [
  { value: "item_name", label: "Tên hàng" },
  { value: "quantity", label: "Số lượng" },
  { value: "unit", label: "Đơn vị" },
  { value: "unit_price", label: "Đơn giá" },
  { value: "amount", label: "Thành tiền" },
];

export const VAI_TRO_CHUNG_TU: { value: string; label: string }[] = [
  { value: "order", label: "Đặt hàng" },
  { value: "offer", label: "Chào giá" },
  { value: "delivery", label: "Giao nhận" },
  { value: "billing", label: "Thanh toán" },
  { value: "other", label: "Khác" },
];

export const MAU_COT = [
  "#fde68a",
  "#bfdbfe",
  "#bbf7d0",
  "#fecaca",
  "#ddd6fe",
  "#fed7aa",
  "#a5f3fc",
  "#fbcfe8",
  "#d9f99d",
  "#e9d5ff",
  "#fecdd3",
  "#c7d2fe",
];
export const MAU_TRUONG = "#f5d0fe";

const AN = new Set(["document_type", "role", "items", "tables", "other_fields"]);
const THANG = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const SO_VN = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 6 });
const SO_EN = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });

export function laCauTrucCu(extraction: Extraction): boolean {
  return !Array.isArray(extraction.tables) && Array.isArray(extraction.items);
}

function bangHopLe(table: unknown): table is Table {
  if (!table || typeof table !== "object") return false;
  const { columns, rows } = table as { columns?: unknown; rows?: unknown };
  if (!Array.isArray(columns) || !Array.isArray(rows)) return false;
  return (
    columns.every((cot) => Boolean(cot) && typeof cot === "object" && typeof cot.header === "string") &&
    rows.every((dong) => Boolean(dong) && typeof dong === "object" && !Array.isArray(dong))
  );
}

export function taoBanNhap(extraction: Extraction, layout: OcrLayout | null): Draft {
  const keys: string[] = laCauTrucCu(extraction) ? [] : [...TRUONG_CHINH];
  for (const key of Object.keys(extraction)) {
    const value = extraction[key];
    if (!AN.has(key) && !keys.includes(key) && value !== null && typeof value !== "object") keys.push(key);
  }
  const scalars = keys.map((key) => {
    const value = extraction[key];
    return {
      key,
      value: value === null || value === undefined ? "" : String(value),
      src: layout?.fields[key] ?? [],
    };
  });
  const others = Object.entries(extraction.other_fields ?? {}).map(([name, value]) => ({
    name,
    value: value === null || value === undefined ? "" : String(value),
    nameSrc: layout?.other[name]?.k ?? [],
    src: layout?.other[name]?.v ?? [],
  }));
  const goc: unknown[] = Array.isArray(extraction.tables) ? extraction.tables : [];
  const khoaBang = !goc.every(bangHopLe);
  const tables = khoaBang
    ? []
    : (goc as Table[]).map((table, t) => {
        const viTri = layout?.tables[t] ?? null;
        const headers = table.columns.map((column) => column.header);
        return {
          columns: table.columns.map((column, c) => ({
            header: column.header,
            role: column.role ?? null,
            src: viTri?.headers[c] ?? [],
          })),
          rows: table.rows.map((row, r) =>
            headers.map((header, c) => ({
              value: row[header] ?? null,
              src: viTri?.rows[r]?.[c] ?? [],
            })),
          ),
          extra: table.rows.map((row) =>
            Object.fromEntries(Object.entries(row).filter(([key]) => !headers.includes(key))),
          ),
          moi: table.rows.map(() => false),
        };
      });
  return {
    role: typeof extraction.role === "string" ? extraction.role : "other",
    scalars,
    others,
    tables,
    khoaBang,
  };
}

export function khoa(ref: WordRef): string {
  return `${ref[0]}:${ref[1]}`;
}

export function sapXep(refs: WordRef[]): WordRef[] {
  const thay = new Set<string>();
  return [...refs]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1])
    .filter((ref) => {
      const k = khoa(ref);
      if (thay.has(k)) return false;
      thay.add(k);
      return true;
    });
}

export function chuCuaKhung(pages: OcrResult["pages"], refs: WordRef[]): string {
  return refs
    .map(([p, i]) => pages[p]?.words?.[i]?.[0] ?? "")
    .filter((chu) => chu !== "")
    .join(" ");
}

export function parseSo(text: string, kieu: KieuSo): number | null {
  const gon = text.replace(/\s/g, "");
  if (!/^[-+]?[\d.,]*\d[\d.,]*$/.test(gon)) return null;
  const than = gon.replace(/^[-+]/, "");
  const cuoi = Math.max(than.lastIndexOf("."), than.lastIndexOf(","));
  let so: number;
  if (cuoi < 0) {
    so = Number(than);
  } else {
    const sau = than.slice(cuoi + 1);
    const haiLoai = than.includes(".") && than.includes(",");
    const nhieuDau = than.replace(/[^.,]/g, "").length > 1;
    const thapPhan = haiLoai || (!nhieuDau && (sau.length !== 3 || kieu === "decimal"));
    so = thapPhan
      ? Number(`${than.slice(0, cuoi).replace(/[.,]/g, "") || "0"}.${sau || "0"}`)
      : Number(than.replace(/[.,]/g, ""));
  }
  if (!Number.isFinite(so)) return null;
  return gon.startsWith("-") ? -so : so;
}

function chuanNgay(text: string): string {
  const hai = (chu: string | number) => String(chu).padStart(2, "0");
  const so = text.match(/\d+/g) ?? [];
  if (so.length === 3) {
    if (so[0].length === 4) return `${so[0]}-${hai(so[1])}-${hai(so[2])}`;
    if (so[2].length === 4) return `${so[2]}-${hai(so[1])}-${hai(so[0])}`;
  }
  const thang = (text.match(/[A-Za-z]{3,}/g) ?? [])
    .map((tu) => THANG.indexOf(tu.slice(0, 3).toLowerCase()))
    .find((vi) => vi >= 0);
  if (so.length === 2 && thang !== undefined) {
    const nam = so.find((s) => s.length === 4);
    const ngay = so.find((s) => s.length <= 2);
    if (nam && ngay) return `${nam}-${hai(thang + 1)}-${hai(ngay)}`;
  }
  return text;
}

function cotLaSo(table: DraftTable, c: number): boolean {
  const role = table.columns[c]?.role;
  if (role === "quantity" || role === "unit_price" || role === "amount") return true;
  if (role === "item_name" || role === "unit") return false;
  const values = table.rows.map((row) => row[c]?.value).filter((v) => v !== null && v !== undefined && v !== "");
  return values.length > 0 && values.filter((v) => typeof v === "number").length * 2 > values.length;
}

function giaTriO(text: string, laSo: boolean, kieu: KieuSo): CellValue {
  if (text === "") return null;
  if (!laSo) return text;
  const so = parseSo(text, kieu);
  return so === null ? text : so;
}

export function hienGiaTri(value: CellValue, kieu: KieuSo): string {
  if (value === null || value === "") return "";
  if (typeof value === "number") return (kieu === "decimal" ? SO_EN : SO_VN).format(value);
  return value;
}

export function maDich(dich: Target): string {
  if (dich.kind === "cell") return `o-${dich.t}-${dich.r}-${dich.c}`;
  if (dich.kind === "header") return `td-${dich.t}-${dich.c}`;
  if (dich.kind === "scalar") return `s-${dich.key}`;
  return `k-${dich.i}-${dich.part}`;
}

export function cungDich(a: Target | null, b: Target | null): boolean {
  return a !== null && b !== null && maDich(a) === maDich(b);
}

export function nhanDich(draft: Draft, dich: Target): string {
  if (dich.kind === "cell") {
    const cot = draft.tables[dich.t]?.columns[dich.c]?.header ?? "";
    return `Bảng ${dich.t + 1} · dòng ${dich.r + 1} · ${cot}`;
  }
  if (dich.kind === "header") return `Bảng ${dich.t + 1} · tiêu đề cột ${dich.c + 1}`;
  if (dich.kind === "scalar") return NHAN_TRUONG[dich.key] ?? dich.key;
  const ten = draft.others[dich.i]?.name || "(chưa đặt tên)";
  return dich.part === "name" ? `Tên của trường bổ sung · ${ten}` : `Trường bổ sung · ${ten}`;
}

export function khungCuaDich(draft: Draft, dich: Target): WordRef[] {
  if (dich.kind === "cell") return draft.tables[dich.t]?.rows[dich.r]?.[dich.c]?.src ?? [];
  if (dich.kind === "header") return draft.tables[dich.t]?.columns[dich.c]?.src ?? [];
  if (dich.kind === "scalar") return draft.scalars.find((s) => s.key === dich.key)?.src ?? [];
  const truong = draft.others[dich.i];
  if (!truong) return [];
  return dich.part === "name" ? truong.nameSrc : truong.src;
}

export function chuCuaDich(draft: Draft, dich: Target): string {
  if (dich.kind === "cell") {
    const value = draft.tables[dich.t]?.rows[dich.r]?.[dich.c]?.value;
    return value === null || value === undefined ? "" : String(value);
  }
  if (dich.kind === "header") return draft.tables[dich.t]?.columns[dich.c]?.header ?? "";
  if (dich.kind === "scalar") return draft.scalars.find((s) => s.key === dich.key)?.value ?? "";
  const truong = draft.others[dich.i];
  if (!truong) return "";
  return dich.part === "name" ? truong.name : truong.value;
}

export function dichKeTiep(draft: Draft, dich: Target): Target | null {
  if (dich.kind !== "cell") return null;
  const table = draft.tables[dich.t];
  if (!table || !table.moi[dich.r] || dich.c + 1 >= table.columns.length) return null;
  return { kind: "cell", t: dich.t, r: dich.r, c: dich.c + 1 };
}

export function datGiaTri(draft: Draft, dich: Target, text: string, src: WordRef[], kieu: KieuSo): Draft {
  if (dich.kind === "cell") {
    return {
      ...draft,
      tables: draft.tables.map((table, t) =>
        t !== dich.t
          ? table
          : {
              ...table,
              rows: table.rows.map((row, r) =>
                r !== dich.r
                  ? row
                  : row.map((cell, c) =>
                      c !== dich.c ? cell : { value: giaTriO(text, cotLaSo(table, c), kieu), src },
                    ),
              ),
            },
      ),
    };
  }
  if (dich.kind === "header") {
    return {
      ...draft,
      tables: draft.tables.map((table, t) =>
        t !== dich.t
          ? table
          : {
              ...table,
              columns: table.columns.map((column, c) =>
                c !== dich.c ? column : { ...column, header: text, src },
              ),
            },
      ),
    };
  }
  if (dich.kind === "scalar") {
    let value = text;
    if (dich.key === "doc_date") value = chuanNgay(text);
    if (SO_NGUYEN.has(dich.key)) {
      const so = parseSo(text, kieu);
      if (so !== null) value = String(so);
    }
    return {
      ...draft,
      scalars: draft.scalars.map((s) => (s.key !== dich.key ? s : { ...s, value, src })),
    };
  }
  return {
    ...draft,
    others: draft.others.map((o, i) => {
      if (i !== dich.i) return o;
      return dich.part === "name"
        ? { ...o, name: text.replace(/\s*[:：]\s*$/, ""), nameSrc: src }
        : { ...o, value: text, src };
    }),
  };
}

function xuat(draft: Draft) {
  let loi: string | null = null;
  const ten = draft.others.map((o) => o.name.trim());
  if (ten.some((t) => !t) || new Set(ten).size !== ten.length) {
    loi = "Tên trường bổ sung phải có nội dung và không trùng nhau.";
  }
  const other: Record<string, string> = Object.fromEntries(draft.others.map((o, i) => [ten[i], o.value]));
  const tables: Table[] = draft.tables.map((table, t) => {
    const headers = table.columns.map((column) => column.header.trim());
    if (headers.some((h) => !h || h.length > 100) || new Set(headers).size !== headers.length) {
      loi = loi ?? `Bảng ${t + 1}: tiêu đề cột phải có nội dung, không trùng nhau và không quá 100 ký tự.`;
    }
    return {
      columns: table.columns.map((column, c) => ({ header: headers[c], role: column.role })),
      rows: table.rows.map((row, r) => ({
        ...table.extra[r],
        ...Object.fromEntries(row.map((cell, c) => [headers[c], cell.value])),
      })),
    };
  });
  const sources: Sources = {
    fields: Object.fromEntries(
      draft.scalars.filter((s) => s.src.length > 0 && s.value !== "").map((s) => [s.key, s.src]),
    ),
    other: Object.fromEntries(draft.others.map((o, i) => [ten[i], { k: o.nameSrc, v: o.src }])),
    tables: draft.tables.map((table) => ({
      headers: table.columns.map((column) => column.src),
      rows: table.rows.map((row) => row.map((cell) => cell.src)),
    })),
  };
  const scalars: Record<string, string> = Object.fromEntries(draft.scalars.map((s) => [s.key, s.value]));
  return { role: draft.role, scalars, other, tables: draft.khoaBang ? null : tables, sources, loi };
}

export function xuatBanNhap(draft: Draft, goc: Draft, kieu: KieuSo) {
  const moi = xuat(draft);
  const cu = xuat(goc);
  let loi = moi.loi;
  const fields: Partial<Extraction> = {};
  if (moi.role !== cu.role) fields.role = moi.role as DocumentRole;
  for (const [key, value] of Object.entries(moi.scalars)) {
    if (value === cu.scalars[key]) continue;
    if (value === "") {
      fields[key] = null;
    } else if (SO_NGUYEN.has(key)) {
      const so = parseSo(value, kieu);
      if (so === null || !Number.isInteger(so)) {
        loi = loi ?? `${NHAN_TRUONG[key] ?? key} phải là số nguyên (đang là «${value}»).`;
      } else {
        fields[key] = so;
      }
    } else if (key === "doc_date" && !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      loi = loi ?? `Ngày chứng từ phải viết dạng năm-tháng-ngày, ví dụ 2024-12-28 (đang là «${value}»).`;
    } else {
      fields[key] = value;
    }
  }
  if (JSON.stringify(moi.other) !== JSON.stringify(cu.other)) fields.other_fields = moi.other;
  if (moi.tables && JSON.stringify(moi.tables) !== JSON.stringify(cu.tables)) fields.tables = moi.tables;
  return {
    fields,
    sources: moi.sources,
    doiNguon: JSON.stringify(moi.sources) !== JSON.stringify(cu.sources),
    loi,
  };
}

export function dichCuaTruong(field: string, extraction: Extraction): { dich: Target | null; nhan: string } {
  const o = /^tables\.(\d+)\.rows\.(\d+)\.(.+)$/.exec(field);
  if (o) {
    const t = Number(o[1]);
    const r = Number(o[2]);
    const columns = Array.isArray(extraction.tables) ? extraction.tables[t]?.columns : undefined;
    const c = Array.isArray(columns) ? columns.findIndex((column) => column?.header === o[3]) : -1;
    return {
      dich: c >= 0 ? { kind: "cell", t, r, c } : null,
      nhan: `Bảng ${t + 1} · dòng ${r + 1} · ${o[3]}`,
    };
  }
  const dong = /^tables\.(\d+)\.rows\.(\d+)$/.exec(field);
  if (dong) {
    const t = Number(dong[1]);
    const r = Number(dong[2]);
    const columns = Array.isArray(extraction.tables) ? extraction.tables[t]?.columns : undefined;
    const vaiTro = (role: string) =>
      Array.isArray(columns) ? columns.findIndex((column) => column?.role === role) : -1;
    const cAmount = vaiTro("amount");
    const cPrice = vaiTro("unit_price");
    const cQty = vaiTro("quantity");
    const c = cAmount >= 0 ? cAmount : cPrice >= 0 ? cPrice : cQty >= 0 ? cQty : -1;
    const ten = c >= 0 ? columns?.[c]?.header ?? "" : "";
    return {
      dich: c >= 0 ? { kind: "cell", t, r, c } : null,
      nhan: `Bảng ${t + 1} · dòng ${r + 1}${ten ? ` · ${ten}` : ""}`,
    };
  }
  const bang = /^tables\.(\d+)$/.exec(field);
  if (bang) return { dich: null, nhan: `Bảng ${Number(bang[1]) + 1}` };
  if (field === "tables") return { dich: null, nhan: "Các bảng" };
  return { dich: { kind: "scalar", key: field }, nhan: NHAN_TRUONG[field] ?? field };
}

export function dichCuaDoiChieu(field: string, extraction: Extraction): { dich: Target | null; nhan: string } {
  const muc = /^items\.(.+)\.(quantity|unit_price|amount|unit)$/.exec(field);
  if (!muc) return dichCuaTruong(field, extraction);
  const ten = muc[1].trim();
  const vaiTro = muc[2] as ColumnRole;
  const bang = Array.isArray(extraction.tables) ? extraction.tables : [];
  for (let t = 0; t < bang.length; t++) {
    const columns = bang[t]?.columns ?? [];
    const cTen = columns.findIndex((column) => column?.role === "item_name");
    const cDich = columns.findIndex((column) => column?.role === vaiTro);
    if (cTen < 0 || cDich < 0) continue;
    const tenCot = columns[cTen]?.header ?? "";
    const cotDich = columns[cDich]?.header ?? "";
    const rows = bang[t]?.rows ?? [];
    for (let r = 0; r < rows.length; r++) {
      const giaTri = rows[r]?.[tenCot];
      if (typeof giaTri === "string" && giaTri.trim() === ten) {
        return {
          dich: { kind: "cell", t, r, c: cDich },
          nhan: `Bảng ${t + 1} · dòng ${r + 1} · ${cotDich}`,
        };
      }
    }
  }
  return { dich: null, nhan: field };
}

export function oBiCo(validation: Validation | undefined, extraction: Extraction): Map<string, string> {
  const ket = new Map<string, string>();
  for (const flag of validation?.flags ?? []) {
    if (flag.code !== "vi_tri") continue;
    const { dich } = dichCuaTruong(flag.field, extraction);
    if (dich?.kind === "cell") ket.set(`${dich.t}:${dich.r}:${dich.c}`, flag.message);
  }
  return ket;
}

export function nhanCuaKhung(draft: Draft, lech: KhungLech[]): Map<string, NhanKhung> {
  const ket = new Map<string, NhanKhung>();
  const dat = (refs: WordRef[], nhan: NhanKhung) => {
    for (const ref of refs) {
      if (!ket.has(khoa(ref))) ket.set(khoa(ref), nhan);
    }
  };
  draft.tables.forEach((table, t) => {
    table.rows.forEach((row, r) => {
      row.forEach((cell, c) => {
        dat(cell.src, {
          loai: "o",
          mau: MAU_COT[c % MAU_COT.length],
          chu: `Bảng ${t + 1} · dòng ${r + 1} · ${table.columns[c]?.header ?? ""}`,
          dich: { kind: "cell", t, r, c },
        });
      });
    });
    table.columns.forEach((column, c) => {
      dat(column.src, {
        loai: "tieu-de",
        mau: MAU_COT[c % MAU_COT.length],
        chu: `Bảng ${t + 1} · tiêu đề cột · ${column.header}`,
        dich: { kind: "header", t, c },
      });
    });
  });
  for (const s of draft.scalars) {
    dat(s.src, {
      loai: "truong",
      mau: MAU_TRUONG,
      chu: NHAN_TRUONG[s.key] ?? s.key,
      dich: { kind: "scalar", key: s.key },
    });
  }
  draft.others.forEach((o, i) => {
    dat(o.src, {
      loai: "truong",
      mau: MAU_TRUONG,
      chu: `Trường bổ sung · ${o.name || "(chưa đặt tên)"}`,
      dich: { kind: "other", i, part: "value" },
    });
    dat(o.nameSrc, {
      loai: "ten-truong",
      mau: MAU_TRUONG,
      chu: `Tên của trường bổ sung · ${o.name || "(chưa đặt tên)"}`,
      dich: { kind: "other", i, part: "name" },
    });
  });
  for (const muc of lech) {
    dat(muc.refs, { loai: "lech", mau: "#dc2626", chu: muc.chu, dich: muc.dich });
  }
  return ket;
}
