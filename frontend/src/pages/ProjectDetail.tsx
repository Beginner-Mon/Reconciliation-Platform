import { AlertTriangle, Check, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, uploadFile } from "../api";
import { DiscrepancyCard } from "../components/DiscrepancyCard";
import { DocumentSidebar } from "../components/DocumentSidebar";
import { DocumentViewer } from "../components/DocumentViewer";
import { EditPanel } from "../components/EditPanel";
import { ExtractionPanel } from "../components/ExtractionPanel";
import { SplitPane } from "../components/SplitPane";
import { WorkflowView } from "../components/WorkflowView";
import { SEVERITY_ORDER } from "../format";
import { useProject } from "../hooks/useProject";
import type { Discrepancy } from "../types";

type TabKey = "extract" | "flags" | "edit";

export function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data, error, loading, refresh, startPolling } = useProject(projectId);

  const [tab, setTab] = useState<TabKey>("extract");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [discrepancies, setDiscrepancies] = useState<Discrepancy[]>([]);
  /** Khung phải chuyển sang màn hình tiến trình khi bấm Xử lý, ở đó tới khi xong. */
  const [showWorkflow, setShowWorkflow] = useState(false);
  /** Chứng từ đã TÍCH CHỌN — khác `selectedId` (chứng từ đang xem ở khung phải). */
  const [checkedIds, setCheckedIds] = useState<string[]>([]);

  const active = data?.run?.is_active ?? false;
  const stopping = active && Boolean(data?.run?.cancel_requested_at);
  const wasActive = useRef(active);

  useEffect(() => {
    if (wasActive.current && !active) {
      setNotice(
        data?.run?.status === "CANCELLED"
          ? "Đã dừng. Chứng từ chưa chạy giữ nguyên trạng thái — tích chọn để chạy đúng cái cần."
          : null,
      );
    }
    wasActive.current = active;
  }, [active, data?.run]);

  const reconciliation = data?.latest_reconciliation ?? null;
  /** Sửa tay không còn tự đối chiếu, nên kết quả có thể đã lỗi thời. */
  const stale = reconciliation?.is_stale ?? false;
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
      if (data.run.status !== "CANCELLED") setTab("flags");
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

  /** MỘT hành động cho mọi phạm vi: chọn 0 chứng từ là cả project.
   *
   *  Chọn hay không quyết định luôn ý nghĩa của lần chạy:
   *
   *    không chọn  -> chỉ chạy cái CHƯA xong (idempotent, tiết kiệm tiền)
   *    có chọn     -> chạy đúng chừng đó, KỂ CẢ đã xong (`force`)
   *
   *  Người dùng đã chủ động tích vào chứng từ đã VALIDATED thì ý họ là "chạy
   *  lại cái này" — bỏ qua nó mới là hành vi khó hiểu.
   */
  async function process(engine: string) {
    if (!projectId || !data) return;

    const chon = data.documents.filter((d) => checkedIds.includes(d.document_id));

    // `force_edited` cho AI ghi đè công review và KHÔNG lấy lại được. Hỏi trước.
    const daSua = chon.filter((d) => (d.edited_fields ?? []).length > 0);
    if (
      daSua.length > 0 &&
      !window.confirm(
        `${daSua.length} chứng từ đã sửa tay:\n` +
          daSua.map((d) => `  • ${d.file_name}`).join("\n") +
          `\n\nChạy lại sẽ ghi đè bằng dữ liệu AI và không lấy lại được. Tiếp tục?`,
      )
    ) {
      return;
    }

    const seChay = data.documents.filter(
      (d) =>
        d.status !== "VALIDATED" &&
        d.status !== "EXTRACTED" &&
        (d.edited_fields ?? []).length === 0,
    );
    if (
      chon.length === 0 &&
      seChay.length > 1 &&
      !window.confirm(
        `Chưa tích chọn chứng từ nào — sẽ xử lý TẤT CẢ ${seChay.length} chứng từ chưa chạy bằng ${engine}.\n\n` +
          `Mỗi chứng từ gọi AI thật và tốn tiền. Tiếp tục?`,
      )
    ) {
      return;
    }

    setShowWorkflow(true);
    await run(
      async () => {
        const result = await api.process(projectId, {
          engine,
          // Bỏ HẲN trường này khi không chọn gì — gửi mảng rỗng là lỗi 400,
          // cố ý, để bỏ chọn hết rồi bấm nhầm không chạy cả project.
          ...(chon.length
            ? {
                document_ids: chon.map((d) => d.document_id),
                force: true,
                force_edited: true,
              }
            : {}),
        });
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
        return `Đang xử lý ${result.processing.length} chứng từ bằng ${engine}${
          skipped ? `, bỏ qua ${skipped} đã xong` : ""
        }.`;
      },
    );
  }

  async function stop() {
    if (!projectId) return;
    await run(
      async () => {
        await api.stopProcess(projectId);
        await refresh();
      },
      () =>
        "Đang dừng — chờ bước đang chạy dở kết thúc. Lời gọi AI đang chạy không thu hồi được.",
    );
  }

  /** Chỉ so các chứng từ với nhau — không gọi AI, không tốn tiền. */
  async function reconcile() {
    if (!projectId) return;
    await run(
      async () => {
        const result = await api.reconcile(projectId);
        await refresh();
        return result;
      },
      (result) => `Đối soát xong: ${result.discrepancy_count} mâu thuẫn.`,
    );
  }

  async function removeDocument(document: { document_id: string; file_name: string }) {
    if (!projectId) return;
    if (!window.confirm(`Xoá ${document.file_name}?`)) return;
    await run(
      async () => {
        await api.deleteDocument(projectId, document.document_id);
        if (selectedId === document.document_id) setSelectedId(null);
        setCheckedIds((prev) => prev.filter((id) => id !== document.document_id));
        await refresh();
      },
      () => `Đã xoá ${document.file_name} và chạy lại đối soát.`,
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
  const coTheDoiChieu = data.documents.some((d) => d.status === "VALIDATED");

  const TABS: { key: TabKey; label: string; badge?: number }[] = [
    { key: "extract", label: "Trích xuất" },
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
          checkedIds={checkedIds}
          running={active}
          stopping={stopping}
          busy={busy}
          canReconcile={coTheDoiChieu}
          reconcileStale={stale}
          onSelect={(document) => {
            setSelectedId(document.document_id);
            if (showWorkflow && !active) setShowWorkflow(false);
          }}
          onToggle={(documentId) =>
            setCheckedIds((truoc) =>
              truoc.includes(documentId)
                ? truoc.filter((id) => id !== documentId)
                : [...truoc, documentId],
            )
          }
          onToggleAll={() =>
            setCheckedIds((truoc) =>
              truoc.length === data.documents.length
                ? []
                : data.documents.map((d) => d.document_id),
            )
          }
          onUpload={upload}
          onProcess={process}
          onStop={stop}
          onReconcile={reconcile}
          onDelete={removeDocument}
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
              <WorkflowView
                documents={data.documents}
                progress={data.progress}
                active={active}
                stopping={stopping}
              />
            </div>
          ) : (
            <SplitPane
              left={(thuGon) => <DocumentViewer document={selected} onCollapse={thuGon} />}
              right={
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

                  <div className="@container min-h-0 flex-1 overflow-y-auto">
                    {tab === "extract" && <ExtractionPanel document={selected} />}
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
                        {/* Nút "Đối chiếu lại" nằm ở sidebar, cạnh nút Xử lý —
                            để thấy rõ đây là hai hành động của hệ thống, chứ
                            không phải một thao tác chôn trong tab kết quả. */}
                        <h3 className="mb-4 font-semibold text-slate-700">
                          {reconciliation.discrepancy_count} mâu thuẫn
                        </h3>

                        {/* Sửa tay KHÔNG còn tự đối chiếu — nếu im lặng thì
                            người review duyệt nhầm số cũ. Server cũng chặn
                            duyệt, đây chỉ là chỗ nói cho người dùng biết. */}
                        {stale && (
                          <p className="mb-4 flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                            <AlertTriangle size={15} className="shrink-0" />
                            {coTheDoiChieu ? (
                              <span>
                                Có chứng từ được sửa sau lần đối chiếu này — bấm{" "}
                                <span className="font-medium">Đối chiếu lại</span> ở
                                bên trái trước khi duyệt.
                              </span>
                            ) : (
                              <span>
                                Có chứng từ được sửa sau lần đối chiếu này, nhưng chưa có chứng từ nào hợp lệ để
                                đối chiếu lại — sửa các chứng từ đang lỗi trước.
                              </span>
                            )}
                          </p>
                        )}

                        {reconciliation.document_ids.length === 0 ? (
                          <p className="py-12 text-center text-slate-500">
                            Chưa có chứng từ nào so sánh được — chứng từ đang lỗi hoặc không nhận ra loại.
                          </p>
                        ) : sorted.length === 0 ? (
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
                                selectedId={selectedId}
                                onEdit={(document) => {
                                  setSelectedId(document.document_id);
                                  setTab("edit");
                                }}
                                onView={(document) => setSelectedId(document.document_id)}
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
                          ) : reconciliation.document_ids.length > 0 ? (
                            <>
                              <button
                                onClick={() =>
                                  reconciliationId &&
                                  run(
                                    async () => {
                                      await api.review(reconciliationId, "REJECTED");
                                      await refresh();
                                    },
                                    () => "Đã từ chối kết quả đối soát.",
                                  )
                                }
                                disabled={busy || active || stale}
                                title={stale ? "Kết quả đã cũ — đối chiếu lại trước" : undefined}
                                className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                              >
                                Từ chối
                              </button>
                              <button
                                onClick={() =>
                                  reconciliationId &&
                                  run(
                                    async () => {
                                      await api.review(reconciliationId, "APPROVED");
                                      await refresh();
                                    },
                                    () => "Đã duyệt kết quả đối soát.",
                                  )
                                }
                                disabled={busy || active || stale}
                                title={stale ? "Kết quả đã cũ — đối chiếu lại trước" : undefined}
                                className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                              >
                                Duyệt kết quả đối soát
                              </button>
                            </>
                          ) : null}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
                </>
              }
            />
          )}
        </main>
      </div>
    </div>
  );
}
