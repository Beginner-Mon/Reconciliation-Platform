import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { LOW_CONFIDENCE } from "../format";
import type { OcrResult } from "../types";

interface Props {
  ocr: OcrResult | null;
  loading: boolean;
  error: string | null;
}

export function OcrText({ ocr, loading, error }: Props) {
  const [showRaw, setShowRaw] = useState(false);
  const [onlyLow, setOnlyLow] = useState(false);

  const pages = ocr?.pages ?? [];
  const lines = pages.flatMap((page) =>
    (page.lines ?? []).map((line) => ({ ...line, page: page.page_number })),
  );
  const laThap = (line: { confidence?: number | null }) =>
    typeof line.confidence === "number" && line.confidence < LOW_CONFIDENCE;
  const lowCount = lines.filter(laThap).length;
  const shown = onlyLow ? lines.filter(laThap) : lines;
  const trungBinh = pages[0]?.mean_token_confidence;

  return (
    <section>
      <button
        onClick={() => setShowRaw((value) => !value)}
        className="flex items-center gap-1 text-sm font-medium text-slate-600 transition hover:text-slate-900"
      >
        {showRaw ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Text OCR thô
        <span className="font-normal text-slate-400">
          — xem khi cần biết lỗi ở khâu đọc hay khâu hiểu
        </span>
      </button>

      {showRaw && (
        <div className="mt-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm text-slate-500">
              {pages.length > 0 && `${pages.length} trang · ${lines.length} dòng`}
            </span>
            <div className="flex items-center gap-2">
              {lowCount > 0 && (
                <button
                  onClick={() => setOnlyLow((value) => !value)}
                  className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs transition ${
                    onlyLow
                      ? "border-amber-400 bg-amber-100 text-amber-900"
                      : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <AlertTriangle size={11} /> {lowCount} dòng đọc không chắc
                </button>
              )}
              {typeof trungBinh === "number" && (
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    trungBinh < 0.85
                      ? "bg-amber-100 text-amber-800"
                      : "bg-emerald-100 text-emerald-800"
                  }`}
                >
                  độ tin cậy trung bình {trungBinh.toFixed(3)}
                </span>
              )}
            </div>
          </div>

          {loading ? (
            <p className="rounded border border-slate-200 bg-white px-3 py-8 text-center text-slate-500">
              Đang tải…
            </p>
          ) : error ? (
            <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {error}
            </p>
          ) : shown.length > 0 ? (
            <div className="max-h-96 overflow-auto rounded border border-slate-200 bg-white">
              <table className="w-full text-sm">
                <tbody>
                  {shown.map((line, index) => {
                    const low = laThap(line);
                    return (
                      <tr
                        key={index}
                        className={`border-b border-slate-100 last:border-0 ${low ? "bg-amber-50" : ""}`}
                      >
                        <td className="w-10 select-none px-2 py-1 text-right align-top text-xs text-slate-400">
                          {line.page}
                        </td>
                        <td
                          className={`px-2 py-1 align-top ${low ? "text-amber-900" : "text-slate-700"}`}
                        >
                          {line.text || <span className="text-slate-300">(dòng trống)</span>}
                        </td>
                        <td className="w-14 px-2 py-1 text-right align-top text-xs tabular-nums">
                          {typeof line.confidence === "number" && (
                            <span className={low ? "text-amber-600" : "text-slate-400"}>
                              {line.confidence.toFixed(2)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-3 text-sm text-slate-700">
              {ocr?.text || "(trống)"}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
