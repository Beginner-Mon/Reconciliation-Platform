import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { LOW_CONFIDENCE, formatValue } from "../format";
import type { DocumentView, OcrResult } from "../types";

/** Hai phần: text OCR đọc được, và các trường AI hiểu thành.
 *
 *  Đặt cạnh nhau để người review biết lỗi nằm ở khâu ĐỌC hay khâu HIỂU —
 *  hai khâu đó sửa bằng hai cách khác nhau.
 */
export function OcrPanel({ document }: { document: DocumentView | null }) {
  const [ocr, setOcr] = useState<OcrResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!document) return;
    let cancelled = false;
    setLoading(true);
    setOcr(null);
    setError(null);
    api
      .getOcr(document.project_id, document.document_id)
      .then((result) => !cancelled && setOcr(result))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [document?.document_id, document?.updated_at]);

  if (!document) {
    return <p className="py-20 text-center text-slate-500">Chọn một chứng từ bên trái.</p>;
  }

  const extraction = document.extraction ?? {};
  const confidence = document.confidence ?? {};
  const page = ocr?.pages?.[0];

  return (
    <div className="space-y-6 p-6">
      {/* Text OCR đọc được */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold text-slate-700">Text OCR đọc được</h3>
          {typeof page?.mean_token_confidence === "number" && (
            <span
              className={`rounded px-2 py-0.5 text-xs ${
                page.mean_token_confidence < 0.85
                  ? "bg-amber-100 text-amber-800"
                  : "bg-emerald-100 text-emerald-800"
              }`}
            >
              độ tin cậy trung bình {page.mean_token_confidence.toFixed(3)}
            </span>
          )}
        </div>

        {loading ? (
          <p className="rounded border border-slate-200 bg-white px-3 py-8 text-center text-slate-500">
            Đang tải…
          </p>
        ) : error ? (
          <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {error}
          </p>
        ) : (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-3 text-sm text-slate-700">
            {ocr?.text || "(trống)"}
          </pre>
        )}

        {page?.key_value_pairs && page.key_value_pairs.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-sm text-slate-600">
              Cặp khoá–giá trị OCR tách được ({page.key_value_pairs.length})
            </summary>
            <table className="mt-2 w-full overflow-hidden rounded border border-slate-200 bg-white text-sm">
              <tbody>
                {page.key_value_pairs.map((kv, index) => (
                  <tr key={index} className="border-b border-slate-100 last:border-0">
                    <td className="px-3 py-1.5 text-slate-600">{kv.key}</td>
                    <td className="px-3 py-1.5 text-slate-900">{kv.value}</td>
                    <td className="w-16 px-2 py-1.5 text-right text-xs">
                      {typeof kv.confidence === "number" && (
                        <span
                          className={
                            kv.confidence < LOW_CONFIDENCE ? "text-amber-600" : "text-slate-400"
                          }
                        >
                          {kv.confidence.toFixed(2)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </section>

      {/* Trường AI trích ra */}
      <section>
        <h3 className="mb-2 font-semibold text-slate-700">Trường AI trích xuất</h3>
        {Object.keys(extraction).length === 0 ? (
          <p className="rounded border border-slate-200 bg-white px-3 py-6 text-center text-slate-500">
            Chưa có dữ liệu trích xuất.
          </p>
        ) : (
          <table className="w-full overflow-hidden rounded border border-slate-200 bg-white text-sm">
            <tbody>
              {Object.entries(extraction)
                .filter(([key]) => key !== "items")
                .map(([key, value]) => {
                  const conf = confidence[key];
                  const low = typeof conf === "number" && conf < LOW_CONFIDENCE;
                  return (
                    <tr key={key} className="border-b border-slate-100 last:border-0">
                      <td className="w-48 px-3 py-1.5 text-slate-600">{key}</td>
                      <td className={`px-3 py-1.5 ${low ? "bg-amber-50 text-amber-900" : "text-slate-900"}`}>
                        {formatValue(value)}
                        {low && <span className="ml-2 text-xs text-amber-600">⚠ {conf.toFixed(2)}</span>}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        )}

        {extraction.items && extraction.items.length > 0 && (
          <table className="mt-3 w-full overflow-hidden rounded border border-slate-200 bg-white text-sm">
            <thead className="bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="px-3 py-1.5 font-medium">Mặt hàng</th>
                <th className="w-20 px-3 py-1.5 text-right font-medium">SL</th>
                <th className="w-32 px-3 py-1.5 text-right font-medium">Đơn giá</th>
              </tr>
            </thead>
            <tbody>
              {extraction.items.map((item, index) => (
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
        )}
      </section>
    </div>
  );
}
