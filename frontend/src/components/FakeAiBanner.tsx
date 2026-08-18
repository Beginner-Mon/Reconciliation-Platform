import { useEffect, useState } from "react";
import { api } from "../api";

/** Cảnh báo backend đang chạy AI giả.
 *
 *  Không có băng này thì tải một PDF thật lên vẫn ra dữ liệu mẫu cố định, nhìn
 *  giống hệt lỗi hệ thống. Đó chính là chuyện đã xảy ra lúc dùng thử v1.
 */
export function FakeAiBanner() {
  const [fake, setFake] = useState(false);

  useEffect(() => {
    api.getDevMeta().then((meta) => setFake(meta?.fake_ai ?? false));
  }, []);

  if (!fake) return null;

  return (
    <div className="border-b border-amber-300 bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
      <span className="font-semibold">⚠ ĐANG DÙNG AI GIẢ</span> — kết quả là dữ liệu mẫu cố
      định, <span className="font-medium">không đọc nội dung file thật</span>. Muốn kết quả
      thật: chạy <code className="rounded bg-amber-200 px-1">devserver --real-ai</code> (gọi
      Document AI + Gemini, có tính phí).
    </div>
  );
}
