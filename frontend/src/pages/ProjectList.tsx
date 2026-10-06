import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import type { Project } from "../types";

export function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    try {
      const { items } = await api.listProjects();
      setProjects(items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await api.createProject(name.trim());
      setName("");
      setCreating(false);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function remove(project: Project) {
    const soChungTu = project.document_count ?? 0;
    if (
      !window.confirm(
        `Xoá project "${project.name}" cùng ${soChungTu} chứng từ, kết quả đối chiếu và lịch sử duyệt?\n\nKhông hoàn tác được trên giao diện.`,
      )
    ) {
      return;
    }
    setDeletingId(project.project_id);
    try {
      await api.deleteProject(project.project_id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="min-h-screen">

      <div className="mx-auto w-full max-w-5xl px-6 py-10">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-slate-800">Project</h1>
          <button
            onClick={() => setCreating((open) => !open)}
            title="Tạo project"
            aria-label="Tạo project"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-sky-600 text-white transition hover:bg-sky-700"
          >
            <Plus size={20} strokeWidth={2.5} />
          </button>
        </div>

        {creating && (
          <form onSubmit={create} className="mt-5 flex gap-2">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tên project, ví dụ: Gói thầu thiết bị CNTT 2026"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
            <button
              type="submit"
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700"
            >
              Tạo
            </button>
          </form>
        )}

        {error && (
          <p className="mt-5 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        {loading ? (
          <p className="py-16 text-center text-slate-500">Đang tải…</p>
        ) : projects.length === 0 ? (
          <p className="py-16 text-center text-slate-500">
            Chưa có project nào. Bấm <span className="font-medium text-sky-700">+</span> để tạo.
          </p>
        ) : (
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <div
                key={project.project_id}
                className="flex min-h-24 items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 transition hover:border-sky-300 hover:shadow-sm"
              >
                <Link to={`/projects/${project.project_id}`} className="min-w-0 flex-1 self-stretch">
                  <span className="block font-medium text-slate-800">{project.name}</span>
                  {project.deleting_at && (
                    <span className="mt-1 block text-xs text-red-600">xoá dở — bấm xoá lại</span>
                  )}
                </Link>
                <span className="flex shrink-0 items-center gap-1">
                  {project.processing_run_id && (
                    <Loader2 size={18} className="animate-spin text-sky-600" />
                  )}
                  <button
                    onClick={() => remove(project)}
                    disabled={
                      Boolean(project.processing_run_id) || deletingId === project.project_id
                    }
                    title={
                      project.processing_run_id
                        ? "Project đang chạy xử lý — dừng run trước khi xoá"
                        : `Xoá project ${project.name}`
                    }
                    aria-label={`Xoá project ${project.name}`}
                    className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                  >
                    {deletingId === project.project_id ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Trash2 size={15} />
                    )}
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
