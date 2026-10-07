import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import {
  chuCuaDich,
  chuCuaKhung,
  cungDich,
  datGiaTri,
  dichKeTiep,
  khoa,
  khungCuaDich,
  nhanCuaKhung,
  oBiCo,
  sapXep,
  taoBanNhap,
  xuatBanNhap,
  type Draft,
  type KhungLech,
  type NhanKhung,
  type Target,
} from "../review/draft";
import type { ColumnRole, DocumentView, OcrResult, WordRef } from "../types";

const CO_OCR = new Set(["VALIDATED", "FAILED"]);

export function useReview(document: DocumentView | null, refresh: () => Promise<unknown>) {
  const [ocr, setOcr] = useState<OcrResult | null>(null);
  const [dangTai, setDangTai] = useState(false);
  const [loiOcr, setLoiOcr] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [goc, setGoc] = useState<Draft | null>(null);
  const [dich, setDich] = useState<Target | null>(null);
  const [xem, setXem] = useState<WordRef | null>(null);
  const [chon, setChon] = useState<WordRef[]>([]);
  const [nhay, setNhay] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const vuaLuu = useRef(false);

  const documentId = document?.document_id;
  const updatedAt = document?.updated_at;

  useEffect(() => {
    setOcr(null);
    setLoiOcr(null);
    setDraft(null);
    setGoc(null);
    setDich(null);
    setXem(null);
    setChon([]);
    setError(null);
    setDangTai(false);
    if (vuaLuu.current) vuaLuu.current = false;
    else setSaved(false);
    if (!document) return;
    const extraction = document.extraction;
    const dung = (ketQua: OcrResult | null) => {
      setOcr(ketQua);
      if (!extraction) return;
      const moi = taoBanNhap(extraction, ketQua?.layout ?? null);
      setDraft(moi);
      setGoc(moi);
    };
    if (!CO_OCR.has(document.status)) {
      dung(null);
      return;
    }
    let huy = false;
    setDangTai(true);
    api
      .getOcr(document.project_id, document.document_id)
      .then((ketQua) => {
        if (!huy) dung(ketQua);
      })
      .catch((err) => {
        if (huy) return;
        setLoiOcr(err instanceof ApiError ? err.message : String(err));
        dung(null);
      })
      .finally(() => {
        if (!huy) setDangTai(false);
      });
    return () => {
      huy = true;
    };
  }, [documentId, updatedAt]);

  const pages = ocr?.pages ?? [];
  const layout = ocr?.layout ?? null;
  const kieu = layout?.number_style ?? null;
  const extraction = document?.extraction;
  const validation = document?.validation;

  const co = useMemo(
    () => (extraction ? oBiCo(validation, extraction) : new Map<string, string>()),
    [validation, extraction],
  );

  const lech = useMemo(() => {
    const ket: KhungLech[] = [];
    if (!draft || !goc) return ket;
    for (const k of co.keys()) {
      const [t, r, c] = k.split(":").map(Number);
      const o = draft.tables[t]?.rows[r]?.[c];
      const cu = goc.tables[t]?.rows[r]?.[c];
      const refs = layout?.tables[t]?.at?.[r]?.[c] ?? [];
      if (!o || !cu || o.value !== cu.value || refs.length === 0) continue;
      const cot = draft.tables[t]?.columns[c]?.header ?? "";
      ket.push({
        refs,
        chu: `Chứng từ ghi chỗ này cho Bảng ${t + 1} · dòng ${r + 1} · ${cot}, nhưng kết quả đang khác`,
        dich: { kind: "cell", t, r, c },
      });
    }
    return ket;
  }, [co, draft, goc, layout]);

  const nhan = useMemo(
    () => (draft ? nhanCuaKhung(draft, lech) : new Map<string, NhanKhung>()),
    [draft, lech],
  );

  const tieuDiem = useMemo<WordRef[]>(() => {
    if (!draft) return [];
    if (dich) {
      const cua = khungCuaDich(draft, dich);
      if (cua.length > 0) return cua;
      if (dich.kind === "cell") return layout?.tables[dich.t]?.at?.[dich.r]?.[dich.c] ?? [];
      return [];
    }
    return xem ? [xem] : [];
  }, [draft, dich, xem, layout]);

  const coThayDoi = useMemo(
    () => draft !== null && goc !== null && JSON.stringify(draft) !== JSON.stringify(goc),
    [draft, goc],
  );

  function capNhat(sua: (cu: Draft) => Draft) {
    setDraft((cu) => (cu ? sua(cu) : cu));
    setSaved(false);
    setError(null);
  }

  function moDich(moi: Target) {
    setXem(null);
    setChon([]);
    setDich(moi);
    setNhay((n) => n + 1);
  }

  function chonDich(moi: Target) {
    if (!draft) return;
    if (chon.length > 0) {
      const refs = sapXep(chon);
      capNhat((cu) => datGiaTri(cu, moi, chuCuaKhung(pages, refs), refs, kieu));
      setChon([]);
      setDich(null);
      return;
    }
    if (cungDich(dich, moi)) {
      setDich(null);
      return;
    }
    moDich(moi);
  }

  function bamKhung(ref: WordRef, shift: boolean) {
    if (!draft) return;
    const k = khoa(ref);
    if (dich) {
      const hienCo = khungCuaDich(draft, dich);
      const daCo = hienCo.some((cu) => khoa(cu) === k);
      const refs = !shift
        ? [ref]
        : daCo
          ? hienCo.filter((cu) => khoa(cu) !== k)
          : sapXep([...hienCo, ref]);
      capNhat((cu) => datGiaTri(cu, dich, chuCuaKhung(pages, refs), refs, kieu));
      if (!shift) setDich(dichKeTiep(draft, dich));
      return;
    }
    if (nhan.has(k)) {
      setChon([]);
      setXem(ref);
      return;
    }
    setXem(null);
  }

  function go(chu: string) {
    if (!draft || !dich) return;
    if (chu === chuCuaDich(draft, dich)) return;
    capNhat((cu) => datGiaTri(cu, dich, chu, [], kieu));
  }

  function layTaiCho() {
    if (!draft || !dich || dich.kind !== "cell") return;
    const refs = sapXep(layout?.tables[dich.t]?.at?.[dich.r]?.[dich.c] ?? []);
    if (refs.length === 0) return;
    capNhat((cu) => datGiaTri(cu, dich, chuCuaKhung(pages, refs), refs, kieu));
    setDich(null);
  }

  function deTrong() {
    if (!draft || !dich) return;
    capNhat((cu) => datGiaTri(cu, dich, "", [], kieu));
    setDich(null);
  }

  function themDong(t: number) {
    const table = draft?.tables[t];
    if (!table) return;
    const r = table.rows.length;
    capNhat((cu) => ({
      ...cu,
      tables: cu.tables.map((bang, i) =>
        i !== t
          ? bang
          : {
              ...bang,
              rows: [...bang.rows, bang.columns.map(() => ({ value: null, src: [] }))],
              extra: [...bang.extra, {}],
              moi: [...bang.moi, true],
            },
      ),
    }));
    moDich({ kind: "cell", t, r, c: 0 });
  }

  function xoaDongCuoi(t: number) {
    capNhat((cu) => ({
      ...cu,
      tables: cu.tables.map((bang, i) =>
        i !== t || bang.rows.length === 0
          ? bang
          : {
              ...bang,
              rows: bang.rows.slice(0, -1),
              extra: bang.extra.slice(0, -1),
              moi: bang.moi.slice(0, -1),
            },
      ),
    }));
    setDich(null);
  }

  function datVaiTroCot(t: number, c: number, role: ColumnRole | null) {
    capNhat((cu) => ({
      ...cu,
      tables: cu.tables.map((bang, i) =>
        i !== t
          ? bang
          : { ...bang, columns: bang.columns.map((cot, j) => (j !== c ? cot : { ...cot, role })) },
      ),
    }));
  }

  function datVaiTro(role: string) {
    capNhat((cu) => ({ ...cu, role }));
  }

  function themTruong() {
    if (!draft) return;
    const i = draft.others.length;
    capNhat((cu) => ({
      ...cu,
      others: [...cu.others, { name: "", value: "", nameSrc: [], src: [] }],
    }));
    moDich({ kind: "other", i, part: "name" });
  }

  function taoTruongTuKhung() {
    if (!draft || chon.length === 0) return;
    const refs = sapXep(chon);
    const i = draft.others.length;
    capNhat((cu) => ({
      ...cu,
      others: [...cu.others, { name: "", value: chuCuaKhung(pages, refs), nameSrc: [], src: refs }],
    }));
    moDich({ kind: "other", i, part: "name" });
  }

  function xoaTruong(i: number) {
    capNhat((cu) => ({ ...cu, others: cu.others.filter((_, j) => j !== i) }));
    setDich(null);
  }

  function hoanTac() {
    setDraft(goc);
    setDich(null);
    setXem(null);
    setChon([]);
    setError(null);
  }

  function nhapTuCache(ban: Draft) {
    setDraft(ban);
    setDich(null);
    setXem(null);
    setChon([]);
    setError(null);
    setSaved(false);
  }

  function re(refs: WordRef[]) {
    window.document
      .querySelectorAll("rect.dang-re")
      .forEach((khung) => khung.classList.remove("dang-re"));
    for (const ref of refs) {
      window.document.querySelector(`rect[data-ref="${khoa(ref)}"]`)?.classList.add("dang-re");
    }
  }

  async function luu() {
    if (!document || !draft || !goc) return;
    const ket = xuatBanNhap(draft, goc, kieu);
    if (ket.loi) {
      setError(ket.loi);
      return;
    }
    const doiDuLieu = Object.keys(ket.fields).length > 0;
    if (!doiDuLieu && !ket.doiNguon) {
      setError("Chưa thay đổi gì.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.editDocument(document.project_id, document.document_id, ket.fields, ket.sources);
      vuaLuu.current = doiDuLieu;
      setGoc(draft);
      setDich(null);
      setSaved(true);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function tatCo(code: string, field: string) {
    if (!document) return;
    await api.dismissFlag(document.project_id, document.document_id, code, field);
    await refresh();
  }

  async function moLaiCo(code: string, field: string) {
    if (!document) return;
    await api.reopenFlag(document.project_id, document.document_id, code, field);
    await refresh();
  }

  return {
    ocr,
    pages,
    layout,
    kieu,
    dangTai,
    loiOcr,
    draft,
    goc,
    coThayDoi,
    co,
    dich,
    xem,
    chon,
    nhan,
    tieuDiem,
    nhay,
    saving,
    error,
    saved,
    chonDich,
    moDich,
    boDich: () => setDich(null),
    boXem: () => setXem(null),
    boChon: () => setChon([]),
    bamKhung,
    go,
    layTaiCho,
    deTrong,
    themDong,
    xoaDongCuoi,
    datVaiTroCot,
    datVaiTro,
    themTruong,
    taoTruongTuKhung,
    xoaTruong,
    hoanTac,
    nhapTuCache,
    re,
    luu,
    tatCo,
    moLaiCo,
  };
}

export type Review = ReturnType<typeof useReview>;
