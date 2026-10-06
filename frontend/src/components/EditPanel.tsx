import { AlertTriangle, Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { LOW_CONFIDENCE, formatMoney } from "../format";
import type { DocumentView, Extraction, LineItem, Table } from "../types";
import { ValidationFlags } from "./ValidationFlags";

/** Sửa tay dữ liệu AI trích sai. Trước đây là modal, giờ là một tab.
 *  Trường có confidence thấp được tô vàng — đó là chỗ OCR hay đọc sai nhất.
 */

const KHONG_SUA = new Set(["document_type", "items"]);

const NHAN: Record<string, string> = {
  vendor: "Nhà cung cấp",
  vendor_tax_code: "Mã số thuế",
  buyer: "Bên mua",
  currency: "Tiền tệ",
  po_number: "Số đơn đặt hàng",
  invoice_number: "Số hóa đơn",
  record_number: "Số biên bản",
  po_date: "Ngày đặt hàng",
  invoice_date: "Ngày hóa đơn",
  record_date: "Ngày nghiệm thu",
  subtotal: "Tiền hàng",
  discount_amount: "Chiết khấu",
  tax_amount: "Thuế",
  total_amount: "Tổng tiền",
  payment_due_date: "Hạn thanh toán",
  delivery_date: "Ngày giao",
  payment_terms: "Điều khoản",
  accepted_by: "Người nghiệm thu",
  notes: "Ghi chú",
};

const LA_SO = new Set(["subtotal", "discount_amount", "tax_amount", "total_amount"]);

function parseNumber(text: string): number {
  return Number(text.replace(/[^\d-]/g, "")) || 0;
}

interface Props {
  document: DocumentView | null;
  onSaved: () => void;
}

export function EditPanel({ document, onSaved }: Props) {
  const extraction = document?.extraction ?? {};
  const confidence = document?.confidence ?? {};

  const scalarKeys = Object.keys(extraction).filter(
    (key) => !KHONG_SUA.has(key) && typeof extraction[key] !== "object",
  );

  const [values, setValues] = useState<Record<string, string>>({});
  const [items, setItems] = useState<LineItem[]>([]);
  const [tables, setTables] = useState<Table[]>([]);
  const [otherFields, setOtherFields] = useState<[string, string][]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Nạp lại form mỗi khi đổi document hoặc dữ liệu được cập nhật.
  useEffect(() => {
    setValues(Object.fromEntries(scalarKeys.map((key) => [key, String(extraction[key] ?? "")])));
    setItems((extraction.items ?? []).map((item) => ({ ...item })));
    setTables(structuredClone(extraction.tables ?? []));
    setOtherFields(Object.entries(extraction.other_fields ?? {}));
    setError(null);
    setSaved(false);
  }, [document?.document_id, document?.updated_at]);

  if (!document) {
    return <p className="py-20 text-center text-slate-500">Chọn một chứng từ bên trái.</p>;
  }
  if (!document.extraction) {
    return (
      <p className="py-20 text-center text-slate-500">
        Chứng từ này chưa có dữ liệu trích xuất để sửa.
      </p>
    );
  }

  const setItem = (index: number, patch: Partial<LineItem>) =>
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  async function save() {
    if (!document) return;
    setSaving(true);
    setError(null);
    try {
      const fields: Partial<Extraction> = {};
      const labels = otherFields.map(([key]) => key.trim());
      if (labels.some((key) => !key) || new Set(labels).size !== labels.length) {
        setError("Nhãn trường bổ sung phải có nội dung và không trùng nhau.");
        return;
      }
      const extra = Object.fromEntries(otherFields.map(([, value], index) => [labels[index], value]));
      if (JSON.stringify(extra) !== JSON.stringify(extraction.other_fields ?? {})) fields.other_fields = extra;
      if (JSON.stringify(tables) !== JSON.stringify(extraction.tables ?? [])) fields.tables = tables;
      for (const key of scalarKeys) {
        const raw = values[key];
        const next = LA_SO.has(key) ? parseNumber(raw) : raw;
        if (next !== extraction[key] && raw !== "") fields[key] = next;
      }
      if (extraction.items && JSON.stringify(items) !== JSON.stringify(extraction.items)) {
        fields.items = items;
      }
      if (Object.keys(fields).length === 0) {
        setError("Chưa thay đổi gì.");
        return;
      }
      await api.editDocument(document.project_id, document.document_id, fields);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const invalid = document.validation && !document.validation.valid;

  return (
    <div className="space-y-4 p-6">
      <ValidationFlags validation={document.validation} />
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-700">Sửa: {document.file_name}</h3>
        {(document.edited_fields?.length ?? 0) > 0 && (
          <span className="rounded bg-violet-100 px-2 py-0.5 text-xs text-violet-700">
            <Pencil size={11} className="inline" /> đã sửa: {document.edited_fields?.join(", ")}
          </span>
        )}
      </div>

      {invalid && (
        <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          Dữ liệu hiện chưa hợp lệ:{" "}
          {[...(document.validation?.schema_errors ?? []), ...(document.validation?.rule_errors ?? [])].join("; ")}
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        {scalarKeys.map((key) => {
          const conf = confidence[key];
          const low = typeof conf === "number" && conf < LOW_CONFIDENCE;
          return (
            <label key={key} className="block">
              <span className="flex items-center gap-1 text-sm text-slate-600">
                {NHAN[key] ?? key}
                {low && (
                  <span
                    className="flex items-center gap-0.5 text-amber-600"
                    title={`AI đọc trường này với độ tin cậy ${conf.toFixed(2)} — nên kiểm lại`}
                  >
                    <AlertTriangle size={12} /> {conf.toFixed(2)}
                  </span>
                )}
              </span>
              <input
                value={values[key] ?? ""}
                onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                className={`mt-1 w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-sky-500 ${
                  low ? "border-amber-400 bg-amber-50" : "border-slate-300"
                }`}
              />
            </label>
          );
        })}
      </div>

      <section className="space-y-2">
        <h3 className="font-semibold">Trường bổ sung theo chứng từ</h3>
        {otherFields.map(([key, value], index) => (
          <div key={index} className="flex gap-2">
            <input aria-label={`Nhãn trường ${index + 1}`} value={key} onChange={(e) => setOtherFields((prev) => prev.map((entry, i) => i === index ? [e.target.value, entry[1]] : entry))} className="w-1/3 rounded border p-2" />
            <textarea aria-label={`Giá trị trường ${index + 1}`} value={value} onChange={(e) => setOtherFields((prev) => prev.map((entry, i) => i === index ? [entry[0], e.target.value] : entry))} className="flex-1 rounded border p-2" />
            <button onClick={() => setOtherFields((prev) => prev.filter((_, i) => i !== index))}>Bỏ trường</button>
          </div>
        ))}
        <button onClick={() => setOtherFields((prev) => [...prev, ["", ""]])} className="text-sky-700">+ Thêm trường</button>
      </section>
      {tables.map((table, ti) => (
        <div key={ti} className="overflow-auto">
          <h3 className="font-semibold">Bảng {ti + 1}</h3>
          <table className="w-full text-sm">
            <thead><tr>{table.columns.map((column) => <th key={column.header} className="border p-2">{column.header}</th>)}</tr></thead>
            <tbody>{table.rows.map((row, ri) => <tr key={ri}>{table.columns.map((column) => (
              <td key={column.header} className="border p-1">
                <input aria-label={`Bảng ${ti + 1}, dòng ${ri + 1}, ${column.header}`} value={row[column.header] ?? ""} readOnly={!column.role}
                  onChange={(e) => setTables((prev) => prev.map((t, i) => i === ti ? { ...t, rows: t.rows.map((r, j) => j === ri ? { ...r, [column.header]: e.target.value === "" ? null : e.target.value } : r) } : t))}
                  className="w-full min-w-24 rounded p-1 read-only:bg-slate-100" />
              </td>
            ))}</tr>)}</tbody>
          </table>
        </div>
      ))}
      {items.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium text-slate-700">Mặt hàng</div>
          <table className="w-full overflow-hidden rounded border border-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="px-2 py-1.5 font-medium">Tên</th>
                <th className="w-24 px-2 py-1.5 font-medium">SL</th>
                <th className="w-40 px-2 py-1.5 font-medium">Đơn giá</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={index} className="border-t border-slate-100">
                  <td className="px-2 py-1">
                    <input
                      value={item.item_name}
                      onChange={(e) => setItem(index, { item_name: e.target.value })}
                      className="w-full rounded border border-slate-300 px-2 py-1 outline-none focus:border-sky-500"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      value={item.quantity}
                      onChange={(e) => setItem(index, { quantity: parseNumber(e.target.value) })}
                      className="w-full rounded border border-slate-300 px-2 py-1 text-right tabular-nums outline-none focus:border-sky-500"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      value={item.unit_price == null ? "" : formatMoney(item.unit_price)}
                      disabled={item.unit_price == null}
                      onChange={(e) => setItem(index, { unit_price: parseNumber(e.target.value) })}
                      className="w-full rounded border border-slate-300 px-2 py-1 text-right tabular-nums outline-none focus:border-sky-500 disabled:bg-slate-100 disabled:text-slate-400"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {error && (
        <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {saved && !error && (
        <p className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Đã lưu. Kết quả đối soát cũ đã lỗi thời — bấm Đối chiếu lại.
        </p>
      )}

      <div className="flex items-center justify-between border-t border-slate-200 pt-4">
        <span className="text-sm text-slate-500">Lưu xong, bấm Đối chiếu lại ở bên trái để cập nhật cảnh báo.</span>
        <button
          onClick={save}
          disabled={saving}
          className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {saving ? "Đang lưu…" : "Lưu"}
        </button>
      </div>
    </div>
  );
}
