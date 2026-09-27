import type { Validation } from "../types";

export function ValidationFlags({ validation }: { validation?: Validation }) {
  if (!validation) return null;
  const flags = validation.flags ?? [];
  const warnings = validation.warnings ?? [];
  if (!flags.length && !warnings.length) return null;
  return (
    <section className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <h3 className="font-semibold">Cần kiểm tra — chưa phải kết luận chứng từ sai</h3>
      {warnings.map((message, index) => <p key={`warning-${index}`}>{message}</p>)}
      {flags.map((flag, index) => (
        <div key={`${flag.code}-${index}`}>
          <p><strong>{flag.field}</strong>: {flag.message}</p>
          {flag.formula && <p>Giả định: {flag.formula}</p>}
          {Object.keys(flag.values).length > 0 && <p>{Object.entries(flag.values).map(([key, value]) => `${key}: ${value ?? "chưa có"}`).join(" · ")}</p>}
        </div>
      ))}
    </section>
  );
}
