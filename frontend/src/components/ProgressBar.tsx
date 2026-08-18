interface Props {
  percent: number;
  label?: string;
  compact?: boolean;
}

export function ProgressBar({ percent, label, compact }: Props) {
  const done = percent >= 100;
  return (
    <div className={compact ? "flex items-center gap-2" : "flex items-center gap-3"}>
      <div
        className={`${compact ? "h-1.5 w-24" : "h-2 flex-1"} overflow-hidden rounded-full bg-slate-200`}
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            done ? "bg-emerald-500" : "bg-sky-500"
          }`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <span
        className={`tabular-nums ${compact ? "text-xs text-slate-500" : "text-sm font-medium text-slate-600"}`}
      >
        {label ?? `${percent}%`}
      </span>
    </div>
  );
}
