import { useState } from "react";
import type { DismissedFlag, Validation } from "../types";

interface Props {
  validation?: Validation;
  nhan?: (field: string) => string;
  onPick?: (field: string) => void;
  coTheBam?: (field: string) => boolean;
  choLuu?: (field: string) => boolean;
  dismissed?: DismissedFlag[];
  onDismiss?: (code: string, field: string) => Promise<void>;
  onReopen?: (code: string, field: string) => Promise<void>;
}

function khoa(code: string, field: string): string {
  return `${code}:${field}`;
}

function giaTri(flag: { values?: Record<string, unknown> }): string {
  return JSON.stringify(flag.values ?? {});
}

export function ValidationFlags({
  validation,
  nhan,
  onPick,
  coTheBam,
  choLuu,
  dismissed,
  onDismiss,
  onReopen,
}: Props) {
  const [loi, setLoi] = useState<string | null>(null);
  const [dangTat, setDangTat] = useState<string | null>(null);

  if (!validation) return null;
  const flags = validation.flags ?? [];
  const warnings = validation.warnings ?? [];
  const tat = new Map<string, DismissedFlag>();
  for (const muc of dismissed ?? []) {
    if (muc?.code && muc?.field) tat.set(khoa(muc.code, muc.field), muc);
  }

  const hien = flags.filter((flag) => {
    const muc = tat.get(khoa(flag.code, flag.field));
    if (!muc) return true;
    return giaTri(muc) !== giaTri(flag);
  });
  const daTat = flags.filter((flag) => {
    const muc = tat.get(khoa(flag.code, flag.field));
    return muc !== undefined && giaTri(muc) === giaTri(flag);
  });

  if (!hien.length && !warnings.length && !daTat.length) return null;

  async function tatCo(code: string, field: string) {
    if (!onDismiss) return;
    setDangTat(khoa(code, field));
    setLoi(null);
    try {
      await onDismiss(code, field);
    } catch (err) {
      setLoi(err instanceof Error ? err.message : String(err));
    } finally {
      setDangTat(null);
    }
  }

  async function moLai(code: string, field: string) {
    if (!onReopen) return;
    setDangTat(khoa(code, field));
    setLoi(null);
    try {
      await onReopen(code, field);
    } catch (err) {
      setLoi(err instanceof Error ? err.message : String(err));
    } finally {
      setDangTat(null);
    }
  }

  return (
    <section className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <h3 className="font-semibold">Cần kiểm tra</h3>
      {warnings.map((message, index) => <p key={`warning-${index}`}>{message}</p>)}
      {hien.map((flag, index) => {
        const ten = nhan ? nhan(flag.field) : flag.field;
        const bamDuoc = !coTheBam || coTheBam(flag.field);
        const daSua = choLuu ? choLuu(flag.field) : false;
        const chiTiet =
          (flag.formula ? `Giả định: ${flag.formula}` : "") +
          (Object.keys(flag.values).length > 0
            ? `${flag.formula ? " · " : ""}${Object.entries(flag.values)
                .map(([key, value]) => `${key}: ${value ?? "chưa có"}`)
                .join(" · ")}`
            : "");
        return (
          <div key={`${flag.code}-${index}`}>
            <p>
              {onPick && bamDuoc ? (
                <button
                  type="button"
                  onClick={() => onPick(flag.field)}
                  title="Bấm để xem chỗ này trên chứng từ"
                  className="text-left font-semibold underline decoration-dotted underline-offset-2 hover:text-amber-950"
                >
                  {ten}
                </button>
              ) : (
                <strong>{ten}</strong>
              )}
              : {flag.message}
            </p>
            {chiTiet && (
              <details className="text-xs text-amber-800">
                <summary className="cursor-pointer hover:underline">Chi tiết</summary>
                <p>{chiTiet}</p>
              </details>
            )}
            {daSua ? (
              <p className="mt-1 text-xs font-medium text-emerald-700">
                Đã sửa chỗ này — bấm Lưu ở cuối trang để cập nhật cảnh báo.
              </p>
            ) : onDismiss && (
              <button
                type="button"
                onClick={() => tatCo(flag.code, flag.field)}
                disabled={dangTat === khoa(flag.code, flag.field)}
                className="mt-1 text-xs text-sky-700 hover:underline disabled:opacity-50"
              >
                {dangTat === khoa(flag.code, flag.field) ? "Đang gửi…" : "Đã kiểm tra, tắt cảnh báo này"}
              </button>
            )}
          </div>
        );
      })}
      {daTat.length > 0 && (
        <div className="space-y-1 border-t border-amber-200 pt-2 text-xs text-slate-600">
          {daTat.map((flag) => {
            const muc = tat.get(khoa(flag.code, flag.field));
            const ten = nhan ? nhan(flag.field) : flag.field;
            return (
              <p key={`tat-${flag.code}-${flag.field}`}>
                Đã kiểm tra {ten}
                {muc?.by ? ` bởi ${muc.by}` : ""}
                {muc?.at ? ` lúc ${muc.at}` : ""}.
                {onReopen && (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => moLai(flag.code, flag.field)}
                      disabled={dangTat === khoa(flag.code, flag.field)}
                      className="text-sky-700 hover:underline disabled:opacity-50"
                    >
                      Mở lại
                    </button>
                  </>
                )}
              </p>
            );
          })}
        </div>
      )}
      {loi && <p className="text-red-700">{loi}</p>}
    </section>
  );
}
