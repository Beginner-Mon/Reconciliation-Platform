import { AlertCircle, AlertOctagon, AlertTriangle, Info } from "lucide-react";
import { DOCUMENT_TYPE_LABEL, SEVERITY_LABEL, SEVERITY_STYLE, formatValue } from "../format";
import type { Severity } from "../types";
import type { Discrepancy, DocumentView } from "../types";

interface Props {
  discrepancy: Discrepancy;
  documents: DocumentView[];
  onEdit: (document: DocumentView) => void;
}

const SEVERITY_ICON: Record<Severity, typeof AlertOctagon> = {
  critical: AlertOctagon,
  high: AlertTriangle,
  medium: AlertCircle,
  low: Info,
};

export function DiscrepancyCard({ discrepancy, documents, onEdit }: Props) {
  const Icon = SEVERITY_ICON[discrepancy.severity];
  const style = SEVERITY_STYLE[discrepancy.severity];
  const byId = new Map(documents.map((d) => [d.document_id, d]));

  return (
    <div className={`rounded-lg border p-4 ${style.box}`}>
      <div className="flex items-start gap-2">
        <Icon size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${style.chip}`}>
              {SEVERITY_LABEL[discrepancy.severity].toUpperCase()}
            </span>
            <span className="font-medium text-slate-800">{discrepancy.field}</span>
          </div>

          <p className="mt-1 text-sm text-slate-700">{discrepancy.explanation}</p>

          {discrepancy.values.length > 0 && (
            <table className="mt-3 w-full max-w-lg overflow-hidden rounded border border-slate-200 bg-white text-sm">
              <tbody>
                {discrepancy.values.map((value) => {
                  const document = byId.get(value.document_id);
                  return (
                    <tr key={value.document_id} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-1.5 text-slate-600">
                        {value.document_type
                          ? DOCUMENT_TYPE_LABEL[value.document_type]
                          : value.document_id}
                      </td>
                      <td className="px-3 py-1.5 text-right font-medium tabular-nums text-slate-900">
                        {formatValue(value.value)}
                      </td>
                      <td className="w-16 px-2 py-1.5 text-right">
                        {document?.extraction && (
                          <button
                            onClick={() => onEdit(document)}
                            className="text-xs text-sky-700 hover:underline"
                          >
                            Sửa
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {typeof discrepancy.difference === "number" && discrepancy.difference !== 0 && (
            <p className="mt-2 text-sm text-slate-500">
              Chênh lệch: <span className="tabular-nums">{formatValue(Math.abs(discrepancy.difference))}</span>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
