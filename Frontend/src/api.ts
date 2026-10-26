import type {
  RouteDraft,
  Metrics,
  PlanResponse,
  TraceEvent,
  Validation,
  ChoiceSelection,
} from "./types";

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`请求失败（${response.status}）`);
  return response.json();
}

export async function streamPlan(
  threadId: string,
  text: string,
  signal: AbortSignal,
  onProgress: (event: {
    node: string;
    phase?: "start" | "complete";
    run_id?: string;
    route_draft?: RouteDraft | null;
    trace: TraceEvent[];
    validation?: Validation;
    metrics?: Metrics;
  }) => void,
  selection?: ChoiceSelection,
): Promise<PlanResponse> {
  const response = await fetch("/api/v1/chat_plan/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      thread_id: threadId,
      text,
      selection,
      interaction_mode: "automatic",
      planning_strategy: "route_first",
    }),
    signal,
  });
  if (!response.ok || !response.body)
    throw new Error(`服务请求失败（${response.status}），请确认后端已启动。`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: PlanResponse | undefined;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = block
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!raw) continue;
        const payload = JSON.parse(raw);
        if (kind === "progress") onProgress(payload);
        if (kind === "result") result = payload;
        if (kind === "error")
          throw new Error(payload.message || "Agent 执行失败");
      }
      if (done) break;
    }
    if (!result) throw new Error("连接提前结束，尚未收到完整结果。请重试。");
    return result;
  } finally {
    reader.releaseLock();
  }
}
