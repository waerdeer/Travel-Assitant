import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  Leaf,
  Loader2,
  ShieldCheck,
  CircleAlert,
} from "lucide-react";
import { stages, statusText } from "../domain";
import type { Metrics, TraceEvent, Validation } from "../types";
interface Props {
  busy: boolean;
  activeNode: string;
  trace: TraceEvent[];
  metrics: Metrics;
  validation: Validation;
  status: string;
  showingSavedRun: boolean;
}
export default function AgentInspector({
  busy,
  activeNode,
  trace,
  metrics,
  validation,
  status,
  showingSavedRun,
}: Props) {
  const [showTrace, setShowTrace] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(
      () => setElapsed((Date.now() - started) / 1000),
      1000,
    );
    return () => clearInterval(timer);
  }, [busy]);
  return (
    <aside className="inspector">
      <div className="inspector-title">
        <span>
          <span className="tiny-dot" /> AGENT WORKSPACE
        </span>
        <span className="version">v0.2</span>
      </div>
      <h2>好计划，有迹可循。</h2>
      <p className="inspector-intro">
        从理解需求到检查结果，
        <br />
        每一步都留下真实的执行记录。
      </p>
      <div className="agent-stages">
        {stages.map((stage, i) => {
          const latest = [...trace]
            .reverse()
            .find((e) => e.stage === stage.key);
          const failed =
            (stage.key === "validate" && latest?.passed === false) ||
            (stage.key === "deliver" &&
              ["blocked", "failed", "needs_revision"].includes(status)) ||
            latest?.status === "failed" ||
            latest?.status === "blocked" ||
            (stage.key === "review_options" &&
              status === "blocked" &&
              !!latest);
          const waiting =
            (stage.key === "deliver" &&
              ["awaiting_choice", "awaiting_clarification", "chat"].includes(
                status,
              )) ||
            (stage.key === "review_options" && status === "awaiting_choice");
          const done =
            !failed &&
            !waiting &&
            trace.some(
              (e) =>
                e.stage === stage.key ||
                (stage.key === "review_options" &&
                  e.stage === "apply_selection") ||
                (stage.key === "research" && e.stage === "tool"),
            );
          const active = busy && activeNode === stage.key;
          const Icon = stage.icon;
          return (
            <div
              className={`agent-stage ${failed ? "stage-failed" : ""} ${done ? "done" : ""} ${active ? "running" : ""}`}
              key={stage.key}
            >
              <div className="stage-icon">
                {active ? (
                  <Loader2 size={17} className="spin" />
                ) : failed ? (
                  <CircleAlert size={17} />
                ) : done ? (
                  <Check size={17} />
                ) : (
                  <Icon size={17} />
                )}
              </div>
              <div>
                <h3>{stage.title}</h3>
                <p>
                  {active
                    ? "正在执行…"
                    : failed
                      ? "未通过，需要调整"
                      : waiting
                        ? "等待你的确认"
                        : stage.detail}
                </p>
              </div>
              <span className="stage-index">0{i + 1}</span>
            </div>
          );
        })}
      </div>
      {status && (
        <div className={`run-status ${status}`}>
          <span className="tiny-dot" />
          {statusText[status] || status}
          {busy && <Loader2 size={12} className="spin" />}
        </div>
      )}
      <div className="inspector-divider" />
      <div className="inspector-subheading">
        {showingSavedRun ? "已保存行程的执行记录" : "本轮执行"}
        <span>OBSERVABILITY</span>
      </div>
      <div className="metric-grid">
        <div>
          <span>工具调用</span>
          <strong>
            {metrics.tool_calls ??
              trace.filter((e) => e.stage === "tool").length}
            <small> 次</small>
          </strong>
        </div>
        <div>
          <span>自动修正</span>
          <strong>
            {metrics.repairs ??
              trace.filter((e) => e.stage === "repair").length}
            <small> 次</small>
          </strong>
        </div>
        <div>
          <span>模型调用</span>
          <strong>
            {metrics.model_calls ?? "—"}
            <small> 次</small>
          </strong>
        </div>
        <div>
          <span>{showingSavedRun ? "生成耗时" : "本轮耗时"}</span>
          <strong>
            {busy
              ? elapsed.toFixed(0)
              : metrics.duration_ms
                ? (metrics.duration_ms / 1000).toFixed(1)
                : "—"}
            <small> s</small>
          </strong>
        </div>
      </div>
      {!!metrics.draft_repairs && (
        <p className="token-note">路线草案修正 · {metrics.draft_repairs} 次</p>
      )}
      {metrics.time_to_draft_ms !== undefined && (
        <p className="token-note">
          首份路线草案 · {(metrics.time_to_draft_ms / 1000).toFixed(1)} s
        </p>
      )}
      {metrics.input_tokens !== undefined && (
        <div className="token-note">
          {metrics.input_tokens.toLocaleString()} input /{" "}
          {(metrics.output_tokens || 0).toLocaleString()} output tokens
        </div>
      )}
      {validation.issues && (
        <div className="validation-summary">
          <div>
            <ShieldCheck size={15} />
            <strong>
              {validation.passed ? "硬约束检查通过" : "发现需要调整的约束"}
            </strong>
          </div>
          {validation.issues.map((issue, i) => (
            <p key={`${issue.code}-${i}`} className={issue.severity}>
              <span>{issue.severity === "error" ? "!" : "·"}</span>
              {issue.message}
            </p>
          ))}
        </div>
      )}
      <button className="trace-toggle" onClick={() => setShowTrace(!showTrace)}>
        查看执行记录{" "}
        <ChevronDown size={15} className={showTrace ? "rotated" : ""} />
      </button>
      {showTrace && (
        <div className="trace-list">
          {trace.length ? (
            trace.map((event, i) => (
              <details key={i}>
                <summary>
                  <span className="trace-index">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  {event.summary ||
                    `${event.tool} · ${event.ok ? `${event.count} 条结果` : "调用失败"}`}
                </summary>
                <pre>{JSON.stringify(event, null, 2)}</pre>
              </details>
            ))
          ) : (
            <p>发起规划后，这里会出现实际执行事件。</p>
          )}
        </div>
      )}
      <div className="agent-principle">
        <Leaf size={18} />
        <p>
          先有依据，再做计划。
          <br />
          <span>有明确的边界，才有安心的旅程。</span>
        </p>
      </div>
    </aside>
  );
}
