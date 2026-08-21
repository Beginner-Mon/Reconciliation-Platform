import { Check, RotateCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, uploadFile } from "../api";
import { DiscrepancyCard } from "../components/DiscrepancyCard";
import { DocumentSidebar } from "../components/DocumentSidebar";
import { DocumentViewer } from "../components/DocumentViewer";
import { EditPanel } from "../components/EditPanel";
import { OcrPanel } from "../components/OcrPanel";
import { WorkflowView } from "../components/WorkflowView";
import { SEVERITY_ORDER } from "../format";
import { useProject } from "../hooks/useProject";
import type { Discrepancy } from "../types";

type TabKey = "document" | "ocr" | "flags" | "edit";

export function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data, error, loading, refresh, startPolling } = useProject(projectId);

  const [tab, setTab] = useState<TabKey>("document");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [discrepancies, setDiscrepancies] = useState<Discrepancy[]>([]);
  /** Khung phải chuyển sang màn hình tiến trình khi bấm Xử lý, ở đó tới khi xong. */
  const [showWorkflow, setShowWorkflow] = useState(false);

  const active = data?.run?.is_active ?? false;
  const reconciliation = data?.latest_reconciliation ?? null;
  const reconciliationId = reconciliation?.reconciliation_id;

  const selected = useMemo(
    () => data?.documents.find((d) => d.document_id === selectedId) ?? null,
    [data, selectedId],
  );

  // Chọn sẵn file đầu tiên cho đỡ phải bấm.
  useEffect(() => {
    if (!selectedId && data?.documents.length) {
      setSelectedId(data.documents[0].document_id);
    }
  }, [data, selectedId]);

  // Xử lý xong thì rời màn hình tiến trình, mở thẳng tab Cảnh báo.
  useEffect(() => {
    if (showWorkflow && !active && data?.run) {
      setShowWorkflow(false);
      setTab("flags");
    }
  }, [active, showWorkflow, data?.run]);

  // Danh sách mâu thuẫn nằm ở S3 nên phải lấy riêng.
  useEffect(() => {
    if (!reconciliationId) {
      setDiscrepancies([]);
      return;
    }
    let cancelled = false;
    api
      .getReconciliation(reconciliationId)
      .then((full) => !cancelled && setDiscrepancies(full.discrepancies ?? []))
      .catch(() => !cancelled && setDiscrepancies([]));
    return () => {
      cancelled = true;
    };
  }, [reconciliationId, reconciliation?.discrepancy_count]);

  async function run<T>(action: () => Promise<T>, done?: (result: T) => string) {
    setBusy(true);
    setProblem(null);
    setNotice(null);
    try {
      const result = await action();
      if (done) setNotice(done(result));
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function upload(files: FileList) {
    if (!projectId || files.length === 0) return;
    await run(
      async () => {
        const { documents } = await api.requestUpload(
          projectId,
          Array.from(files).map((f) => f.name),
        );
        for (const target of documents) {
          const file = Array.from(files).find((f) => f.name === target.file_name);
          if (file) await uploadFile(target, file);
        }
        await refresh();
        return documents.length;
      },
      (count) => `Đã tải lên ${count} chứng từ. Bấm Xử lý để chạy.`,
    );
  }

  async function process() {
    if (!projectId) return;
    setShowWorkflow(true);
    await run(
      async () => {
        const result = await api.process(projectId);
        await startPolling();
        return result;
      },
      (result) => {
        const skipped = result.skipped.length;
        if (result.processing.length === 0) {
          setShowWorkflow(false);
          setTab("flags");
          return `Mọi chứng từ đã xử lý, chỉ chạy lại đối soát${skipped ? ` (bỏ qua ${skipped})` : ""}.`;
        }
        return `Đang xử lý ${result.processing.length} chứng từ${
          skipped ? `, bỏ qua ${skipped} đã xong` : ""
        }.`;
      },
    );
  }

  if (loading) return <p className="p-8 text-center text-slate-500">Đang tải…</p>;
  if (error && !data) {
    return (
      <div className="p-8">
        <a href="/" className="text-sm text-sky-700 hover:underline">
          ← Danh sách project
        </a>
        <p className="mt-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      </div>
    );
  }
  if (!data) return null;

  const sorted = [...discrepancies].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );
  const decided = reconciliation && reconciliation.status !== "PENDING_REVIEW";

  const TABS: { key: TabKey; label: string; badge?: number }[] = [
    { key: "document", label: "Tài liệu" },
    { key: "ocr", label: "Kết quả OCR" },
    { key: "flags", label: "Cảnh báo", badge: reconciliation?.discrepancy_count },
    { key: "edit", label: "Sửa" },
  ];

  return (
    <div className="flex h-screen flex-col">

      <div className="flex min-h-0 flex-1">
        <DocumentSidebar
          projectName={data.project.name}
          documents={data.documents}
          selectedId={selectedId}
          running={active}
          busy={busy}
          onSelect={(document) => {
            setSelectedId(document.document_id);
            if (showWorkflow && !active) setShowWorkflow(false);
          }}
          onUpload={upload}
          onProcess={process}
        />

        {/* Khung phải — mọi thứ về xử lý và xem kết quả đều ở đây */}
        <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
          {(notice || problem) && (
            <div className="border-b border-slate-200 px-4 py-2">
              {notice && <p className="text-sm text-sky-800">{notice}</p>}
              {problem && <p className="text-sm text-red-700">{problem}</p>}
            </div>
          )}

          {showWorkflow || active ? (
            <div className="flex-1 overflow-y-auto">
              <WorkflowView documents={data.documents} progress={data.progress} active={active} />
            </div>
          ) : (
            <>
              <nav className="flex shrink-0 gap-1 border-b border-slate-200 bg-white px-3">
                {TABS.map((entry) => (
                  <button
                    key={entry.key}
                    onClick={() => setTab(entry.key)}
                    className={`-mb-px border-b-2 px-4 py-2.5 text-sm transition ${
                      tab === entry.key
                        ? "border-sky-500 font-medium text-sky-700"
                        : "border-transparent text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {entry.label}
                    {entry.badge ? (
                      <span className="ml-1.5 rounded-full bg-red-100 px-1.5 text-xs text-red-700">
                        {entry.badge}
                      </span>
                    ) : null}
                  </button>
                ))}
              </nav>

              <div className="min-h-0 flex-1 overflow-y-auto">
                {tab === "document" && <DocumentViewer document={selected} />}
                {tab === "ocr" && <OcrPanel document={selected} />}
                {tab === "edit" && (
                  <EditPanel
                    document={selected}
                    onSaved={async () => {
                      await refresh();
                    }}
                  />
                )}
                {tab === "flags" && (
                  <div className="p-6">
                    {!reconciliation ? (
                      <p className="py-16 text-center text-slate-500">
                        Chưa có kết quả đối soát. Bấm Xử lý ở bên trái.
                      </p>
                    ) : (
                      <>
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="font-semibold text-slate-700">
                            {reconciliation.discrepancy_count} mâu thuẫn
                          </h3>
                          <button
                            onClick={() =>
                              projectId &&
                              run(
                                async () => {
                                  const result = await api.reconcile(projectId);
                                  await refresh();
                                  return result;
                                },
                                (result) => `Đối soát xong: ${result.discrepancy_count} mâu thuẫn.`,
                              )
                            }
                            disabled={busy || active}
                            className="flex items-center gap-1.5 rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          >
                            <RotateCw size={14} /> Đối soát lại
                          </button>
                        </div>

                        {sorted.length === 0 ? (
                          <p className="flex items-center justify-center gap-2 py-12 text-center text-emerald-700"><Check size={18} />
                            Không tìm thấy mâu thuẫn nào giữa các chứng từ.
                          </p>
                        ) : (
                          <div className="space-y-3">
                            {sorted.map((discrepancy, index) => (
                              <DiscrepancyCard
                                key={`${discrepancy.rule_id}-${discrepancy.field}-${index}`}
                                discrepancy={discrepancy}
                                documents={data.documents}
                                onEdit={(document) => {
                                  setSelectedId(document.document_id);
                                  setTab("edit");
                                }}
                              />
                            ))}
                          </div>
                        )}

                        <div className="mt-6 flex items-center justify-end gap-2 border-t border-slate-200 pt-4">
                          {decided ? (
                            <span
                              className={`rounded px-3 py-1.5 text-sm font-medium ${
                                reconciliation.status === "APPROVED"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-red-100 text-red-800"
                              }`}
                            >
                              {reconciliation.status === "APPROVED" ? (
                                <span className="flex items-center gap-1"><Check size={14} /> Đã duyệt</span>
                              ) : (
                                <span className="flex items-center gap-1"><X size={14} /> Đã từ chối</span>
                              )}
                            </span>
                          ) : (
                            <>
                              <button
                                onClick={() =>
                                  reconciliationId &&
                                  run(
                                    async () => {
                                      await api.reject(reconciliationId);
                                      await refresh();
                                    },
                                    () => "Đã từ chối kết quả đối soát.",
                                  )
                                }
                                disabled={busy || active}
                                className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                              >
                                Từ chối
                              </button>
                              <button
                                onClick={() =>
                                  reconciliationId &&
                                  run(
                                    async () => {
                                      await api.approve(reconciliationId);
                                      await refresh();
                                    },
                                    () => "Đã duyệt kết quả đối soát.",
                                  )
                                }
                                disabled={busy || active}
                                className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                              >
                                Duyệt kết quả đối soát
                              </button>
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
