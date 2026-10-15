import type { Project, Reconciliation } from "./types";

/** Chứng từ gốc của từng chứng từ, suy từ lượt đối chiếu mới nhất.
 *
 *  Chỉ nhóm có ĐÚNG 2 chứng từ mới so cặp với chứng từ gốc (core/crosscheck.py);
 *  nhóm 1 chứng từ không có gì để so, nhóm từ 3 chứng từ chỉ chạy luật cộng dồn.
 *  Server vẫn ghi `anchor_document_id` cho MỌI nhóm, nên phải lọc ở đây: gắn
 *  nhãn gốc cho nhóm không dùng tới nó là báo sai cho người dùng.
 */
export interface AnchorInfo {
  anchorId: string;
  isAnchor: boolean;
  /** Gốc do người dùng chọn (PUT /anchor), không phải hệ thống tự chọn theo vai trò. */
  chosenByUser: boolean;
}

export function anchorsByDocument(
  reconciliation: Reconciliation | null,
  project: Project,
): Map<string, AnchorInfo> {
  const daChon = new Set(project.anchor_document_ids ?? []);
  const ketQua = new Map<string, AnchorInfo>();
  for (const nhom of reconciliation?.groups ?? []) {
    const goc = nhom.anchor_document_id;
    if (!goc || nhom.document_ids.length !== 2) continue;
    for (const id of nhom.document_ids) {
      ketQua.set(id, { anchorId: goc, isAnchor: id === goc, chosenByUser: daChon.has(goc) });
    }
  }
  return ketQua;
}
