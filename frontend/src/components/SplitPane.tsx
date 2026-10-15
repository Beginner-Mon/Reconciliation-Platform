import { PanelLeftOpen } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

interface Props {
  /** Nhận hàm thu gọn để khung trái tự đặt nút "ẩn" vào header của nó. */
  left: (thuGon: () => void) => ReactNode;
  right: ReactNode;
}

const KHOA_TI_LE = "recon.split.ratio";
const KHOA_AN = "recon.split.collapsed";
const MAC_DINH = 0.5;
const NHO_NHAT = 0.3;
const LON_NHAT = 0.7;
const BUOC_PHIM = 0.02;

function kep(giaTri: number): number {
  return Math.min(LON_NHAT, Math.max(NHO_NHAT, giaTri));
}

function docTiLe(): number {
  try {
    const tho = window.localStorage.getItem(KHOA_TI_LE);
    const so = tho === null ? NaN : Number(tho);
    if (typeof so === "number" && Number.isFinite(so)) return kep(so);
  } catch {
    // Chế độ ẩn danh chặn localStorage — cứ dùng mặc định.
  }
  return MAC_DINH;
}

function docAn(): boolean {
  try {
    return window.localStorage.getItem(KHOA_AN) === "1";
  } catch {
    return false;
  }
}

function ghiTiLe(tiLe: number) {
  try {
    window.localStorage.setItem(KHOA_TI_LE, String(tiLe));
  } catch {
    // Không nhớ được thì thôi, lần sau mở lại về mặc định.
  }
}

function ghiAn(an: boolean) {
  try {
    window.localStorage.setItem(KHOA_AN, an ? "1" : "0");
  } catch {
    // Như trên.
  }
}

/** Khung chia đôi ngang: file gốc bên trái, kết quả bên phải. */
export function SplitPane({ left, right }: Props) {
  const khung = useRef<HTMLDivElement>(null);
  const [tiLe, setTiLe] = useState<number>(docTiLe);
  const [an, setAn] = useState<boolean>(docAn);
  const [dangKeo, setDangKeo] = useState(false);

  function thuGon() {
    setAn(true);
    ghiAn(true);
  }

  function moLai() {
    setAn(false);
    ghiAn(false);
  }

  function datTiLe(moi: number) {
    setTiLe(kep(moi));
  }

  return (
    <div ref={khung} className="flex min-h-0 flex-1">
      <div
        style={{ width: `${tiLe * 100}%` }}
        className={`min-w-0 shrink-0 ${an ? "hidden" : ""} ${
          // PDF nằm trong iframe; con trỏ lướt qua iframe là sự kiện chuột
          // chui vào tài liệu bên trong và thao tác kéo đứng khựng giữa chừng,
          // nên lúc kéo phải chặn iframe nhận sự kiện ở cả hai khung.
          dangKeo ? "pointer-events-none select-none" : ""
        }`}
      >
        {left(thuGon)}
      </div>

      {!an && (
        <div
          role="separator"
          aria-orientation="vertical"
          tabIndex={0}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            setDangKeo(true);
          }}
          onPointerMove={(event) => {
            if (!dangKeo || !khung.current) return;
            const rect = khung.current.getBoundingClientRect();
            if (rect.width === 0) return;
            datTiLe((event.clientX - rect.left) / rect.width);
          }}
          onPointerUp={(event) => {
            if (!dangKeo) return;
            setDangKeo(false);
            // Tính lại từ vị trí thả để ghi đúng tỉ lệ cuối, vì state tiLe
            // trong closure có thể còn là giá trị của nhịp pointermove trước.
            if (khung.current) {
              const rect = khung.current.getBoundingClientRect();
              if (rect.width !== 0) {
                const cuoi = kep((event.clientX - rect.left) / rect.width);
                setTiLe(cuoi);
                ghiTiLe(cuoi);
              }
            }
          }}
          onPointerCancel={() => setDangKeo(false)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              const moi = kep(tiLe - BUOC_PHIM);
              setTiLe(moi);
              ghiTiLe(moi);
            } else if (event.key === "ArrowRight") {
              const moi = kep(tiLe + BUOC_PHIM);
              setTiLe(moi);
              ghiTiLe(moi);
            }
          }}
          onDoubleClick={() => {
            setTiLe(MAC_DINH);
            ghiTiLe(MAC_DINH);
          }}
          className="w-1.5 shrink-0 cursor-col-resize bg-slate-200 hover:bg-sky-400"
        />
      )}

      {an && (
        <div className="w-9 shrink-0 border-r border-slate-200 bg-white">
          <button
            onClick={moLai}
            title="Hiện file gốc"
            aria-label="Hiện file gốc"
            className="mx-auto mt-2 flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>
      )}

      <div
        className={`flex min-w-0 flex-1 flex-col ${
          dangKeo ? "pointer-events-none select-none" : ""
        }`}
      >
        {right}
      </div>
    </div>
  );
}
