import type { Review } from "../hooks/useReview";
import { khoa } from "../review/draft";
import type { OcrWord } from "../types";

interface Props {
  page: number;
  words: OcrWord[];
  review: Review;
}

export function PageOverlay({ page, words, review }: Props) {
  const tieuDiem = new Set(review.tieuDiem.map(khoa));
  const chon = new Set(review.chon.map(khoa));

  return (
    <svg
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full"
      style={{ mixBlendMode: "multiply" }}
    >
      {words.map((word, i) => {
        const k = `${page}:${i}`;
        const nhan = review.nhan.get(k);
        let nen = "#ffffff";
        let doDam = 0;
        let vien = "#94a3b8";
        let doDay = 0.5;
        let net: string | undefined;
        if (nhan?.loai === "o") {
          nen = nhan.mau;
          doDam = 0.75;
          vien = "#64748b";
        } else if (nhan?.loai === "tieu-de") {
          nen = nhan.mau;
          doDam = 0.75;
          vien = "#334155";
          doDay = 1;
          net = "3 2";
        } else if (nhan?.loai === "truong") {
          nen = nhan.mau;
          doDam = 0.75;
          vien = "#a21caf";
        } else if (nhan?.loai === "ten-truong") {
          nen = nhan.mau;
          doDam = 0.35;
          vien = "#a21caf";
          net = "3 2";
        } else if (nhan?.loai === "lech") {
          vien = "#dc2626";
          doDay = 2.5;
        }
        if (chon.has(k)) {
          nen = "#fde047";
          doDam = 0.8;
          vien = "#0f172a";
          doDay = 2.5;
          net = undefined;
        }
        if (tieuDiem.has(k)) {
          vien = "#1d4ed8";
          doDay = 3.5;
          net = undefined;
        }
        return (
          <rect
            key={i}
            data-ref={k}
            x={word[1]}
            y={word[2]}
            width={Math.max(word[3] - word[1], 0)}
            height={Math.max(word[4] - word[2], 0)}
            fill={nen}
            fillOpacity={doDam}
            stroke={vien}
            strokeWidth={doDay}
            strokeDasharray={net}
            vectorEffect="non-scaling-stroke"
            pointerEvents="all"
            className="cursor-pointer"
            onClick={(event) => review.bamKhung([page, i], event.shiftKey)}
          >
            <title>{`«${word[0]}» — ${nhan ? nhan.chu : "chưa đưa vào kết quả"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
