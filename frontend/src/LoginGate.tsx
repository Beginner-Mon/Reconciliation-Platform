import { useEffect, useState } from "react";
import { Hub } from "aws-amplify/utils";
import { coCognito, dangNhap, dangXuat, datMatKhauMoi, kiemTraDaDangNhap } from "./auth";

export function LoginGate({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [needNewPassword, setNeedNewPassword] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!coCognito()) {
      setAuthed(true);
      setChecked(true);
      return;
    }
    kiemTraDaDangNhap()
      .then((ok) => setAuthed(ok))
      .catch(() => setAuthed(false))
      .finally(() => setChecked(true));

    const unsub = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedOut") {
        setAuthed(false);
        setChecked(true);
        setNeedNewPassword(false);
      }
    });
    return () => unsub();
  }, []);

  if (!coCognito()) return <>{children}</>;
  if (!checked) return <div className="p-8 text-center text-slate-500">Đang kiểm tra đăng nhập...</div>;
  if (authed) {
    return (
      <>
        <div className="flex justify-end p-2">
          <button
            onClick={async () => {
              await dangXuat();
              location.reload();
            }}
            className="text-sm text-slate-600 underline"
          >
            Đăng xuất
          </button>
        </div>
        {children}
      </>
    );
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const out = await dangNhap(username.trim(), password);
      if (out.nextStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") {
        setNeedNewPassword(true);
      } else if (out.nextStep === "DONE") {
        setAuthed(true);
      } else {
        setError(`Bước tiếp theo không hỗ trợ: ${out.nextStep}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleNewPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const out = await datMatKhauMoi(newPassword);
      if (out.nextStep === "DONE") {
        setAuthed(true);
        setNeedNewPassword(false);
      } else {
        setError(`Bước tiếp theo không hỗ trợ: ${out.nextStep}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (needNewPassword) {
    return (
      <div className="mx-auto mt-24 max-w-sm rounded border bg-white p-6 shadow">
        <h1 className="mb-2 text-lg font-semibold">Đặt mật khẩu mới</h1>
        <p className="mb-4 text-sm text-slate-600">Tài khoản vừa được tạo, cần đổi mật khẩu lần đầu.</p>
        <form onSubmit={handleNewPassword} className="space-y-3">
          <input
            type="password"
            placeholder="Mật khẩu mới"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full rounded border px-3 py-2"
            required
          />
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button type="submit" disabled={loading} className="w-full rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
            {loading ? "Đang xử lý..." : "Xác nhận"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded border bg-white p-6 shadow">
      <h1 className="mb-4 text-lg font-semibold">Đăng nhập</h1>
      <form onSubmit={handleLogin} className="space-y-3">
        <input
          type="text"
          placeholder="Tên đăng nhập"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full rounded border px-3 py-2"
          required
        />
        <input
          type="password"
          placeholder="Mật khẩu"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded border px-3 py-2"
          required
        />
        {error && <div className="text-sm text-red-600">{error}</div>}
        <button type="submit" disabled={loading} className="w-full rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
          {loading ? "Đang đăng nhập..." : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}
