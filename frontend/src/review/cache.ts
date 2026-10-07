import type { Draft } from "./draft";

const HAN_MS = 90 * 60 * 1000;

export interface BanNhap {
  base: string | null;
  luc: number;
  draft: Draft;
}

function khoaLuu(projectId: string, documentId: string): string {
  return `nhap:${projectId}:${documentId}`;
}

export function luuNhap(projectId: string, documentId: string, base: string | null, draft: Draft): void {
  try {
    const duLieu: BanNhap = { base, luc: Date.now(), draft };
    window.localStorage.setItem(khoaLuu(projectId, documentId), JSON.stringify(duLieu));
  } catch {
    return;
  }
}

export function docNhap(projectId: string, documentId: string, base: string | null): Draft | null {
  try {
    const tho = window.localStorage.getItem(khoaLuu(projectId, documentId));
    if (!tho) return null;
    const duLieu = JSON.parse(tho) as BanNhap;
    if (!duLieu || duLieu.base !== base) {
      window.localStorage.removeItem(khoaLuu(projectId, documentId));
      return null;
    }
    if (typeof duLieu.luc !== "number" || Date.now() - duLieu.luc > HAN_MS) {
      window.localStorage.removeItem(khoaLuu(projectId, documentId));
      return null;
    }
    if (!duLieu.draft || typeof duLieu.draft !== "object") return null;
    return duLieu.draft as Draft;
  } catch {
    return null;
  }
}

export function xoaNhap(projectId: string, documentId: string): void {
  try {
    window.localStorage.removeItem(khoaLuu(projectId, documentId));
  } catch {
    return;
  }
}
