import { GlobalWorkerOptions, getDocument } from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState, type ReactNode } from "react";

GlobalWorkerOptions.workerSrc = workerUrl;

const DO_NET = 2;

function PdfPage({
  pdf,
  number,
  children,
}: {
  pdf: PDFDocumentProxy;
  number: number;
  children: ReactNode;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [tiLe, setTiLe] = useState(1 / 1.414);

  useEffect(() => {
    let huy = false;
    let task: RenderTask | null = null;
    pdf
      .getPage(number)
      .then((page) => {
        const dich = canvas.current;
        if (huy || !dich) return;
        const context = dich.getContext("2d");
        if (!context) return;
        const viewport = page.getViewport({ scale: DO_NET });
        dich.width = viewport.width;
        dich.height = viewport.height;
        setTiLe(viewport.width / viewport.height);
        task = page.render({ canvasContext: context, viewport });
        task.promise.catch(() => undefined);
      })
      .catch(() => undefined);
    return () => {
      huy = true;
      task?.cancel();
    };
  }, [pdf, number]);

  return (
    <div className="relative mb-3 bg-white shadow" style={{ aspectRatio: String(tiLe) }}>
      <canvas ref={canvas} className="block h-full w-full" />
      {children}
    </div>
  );
}

export function PdfPages({ url, children }: { url: string; children: (page: number) => ReactNode }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loi, setLoi] = useState<string | null>(null);

  useEffect(() => {
    let huy = false;
    setPdf(null);
    setLoi(null);
    const task = getDocument({ url, disableRange: true, disableStream: true });
    task.promise.then(
      (tai) => {
        if (!huy) setPdf(tai);
      },
      (err: unknown) => {
        if (!huy) setLoi(err instanceof Error ? err.message : String(err));
      },
    );
    return () => {
      huy = true;
      void task.destroy();
    };
  }, [url]);

  if (loi) {
    return (
      <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        Không vẽ được PDF ở đây ({loi}). Bấm «Mở tab mới» ở trên để xem file gốc.
      </p>
    );
  }
  if (!pdf) return <p className="py-20 text-center text-slate-500">Đang tải PDF…</p>;

  return (
    <>
      {Array.from({ length: pdf.numPages }, (_, index) => (
        <PdfPage key={index} pdf={pdf} number={index + 1}>
          {children(index)}
        </PdfPage>
      ))}
    </>
  );
}
