import { stages, statusText } from "./domain";
import CityArt from "./components/CityArt";
import AgentInspector from "./components/AgentInspector";
import TravelPlan from "./components/TravelPlan";
import RouteDraftCard from "./components/RouteDraftCard";
import ChoicePanel from "./components/ChoicePanel";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowUp,
  ChevronRight,
  CircleHelp,
  Compass,
  Download,
  Globe2,
  Loader2,
  MapPin,
  Menu,
  MessageSquare,
  Plus,
  Route,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJson, streamPlan } from "./api";
import type {
  RouteDraft,
  Conversation,
  Message,
  Metrics,
  SavedPlan,
  TraceEvent,
  Validation,
  ChoiceSelection,
  PendingChoice,
} from "./types";

function dateAfter(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function remember(id: string) {
  try {
    localStorage.setItem("travel-thread", id);
  } catch {
    /* optional convenience */
  }
}
function initialThread() {
  try {
    return localStorage.getItem("travel-thread") || crypto.randomUUID();
  } catch {
    return crypto.randomUUID();
  }
}
const greeting: Message = {
  id: "welcome",
  role: "assistant",
  content:
    "你好，我是你的旅行规划助手。告诉我想去的城市、出行日期和偏好，我们一起把旅程安排妥当。",
};

export default function App() {
  const [thread, setThread] = useState(initialThread);
  const [history, setHistory] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([greeting]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [saved, setSaved] = useState<SavedPlan>();
  const [routeDraft, setRouteDraft] = useState<RouteDraft>();
  const [pendingChoice, setPendingChoice] = useState<PendingChoice>();
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [metrics, setMetrics] = useState<Metrics>({});
  const [validation, setValidation] = useState<Validation>({});
  const [status, setStatus] = useState("");
  const [showingSavedRun, setShowingSavedRun] = useState(false);
  const [activeNode, setActiveNode] = useState("");
  const [error, setError] = useState("");
  const [health, setHealth] = useState<
    "checking" | "ok" | "degraded" | "offline"
  >("checking");
  const [mobileNav, setMobileNav] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [visibleMessages, setVisibleMessages] = useState(6);
  const bottom = useRef<HTMLDivElement>(null);
  const draftRef = useRef<HTMLDivElement>(null);
  const choiceRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController>();
  const selection = useRef(0);
  const pendingText = useRef("");

  async function refreshHistory() {
    try {
      const data = await getJson<{ items: Conversation[] }>(
        "/api/v1/conversations?limit=30",
      );
      setHistory(data.items);
    } catch {
      /* Connection state is shown in the header. */
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    const bootstrapVersion = selection.current;
    getJson<{ status: string }>("/health", controller.signal)
      .then((data) => setHealth(data.status === "ok" ? "ok" : "degraded"))
      .catch((err) => {
        if (err.name !== "AbortError") setHealth("offline");
      });
    getJson<{ items: Conversation[] }>(
      "/api/v1/conversations?limit=30",
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted || bootstrapVersion !== selection.current)
          return;
        setHistory(data.items);
        if (data.items.some((item) => item.thread_id === thread))
          void openConversation(thread);
        else setLoadingHistory(false);
      })
      .catch(() => {
        if (
          !controller.signal.aborted &&
          bootstrapVersion === selection.current
        )
          setLoadingHistory(false);
      });
    return () => {
      controller.abort();
      abort.current?.abort();
    };
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);
  useEffect(() => {
    if (routeDraft)
      draftRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [routeDraft?.draft_id]);
  useEffect(() => {
    if (pendingChoice)
      choiceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [pendingChoice?.token]);
  useEffect(() => {
    if (!mobileNav && !showAbout) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileNav(false);
        setShowAbout(false);
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileNav, showAbout]);

  function reset() {
    selection.current += 1;
    abort.current?.abort();
    const id = crypto.randomUUID();
    setThread(id);
    remember(id);
    setMessages([greeting]);
    setVisibleMessages(6);
    setSaved(undefined);
    setRouteDraft(undefined);
    setPendingChoice(undefined);
    setTrace([]);
    setMetrics({});
    setValidation({});
    setStatus("");
    setShowingSavedRun(false);
    setActiveNode("");
    setError("");
    setInput("");
    setBusy(false);
    setLoadingHistory(false);
    setMobileNav(false);
  }
  async function openConversation(id: string) {
    if (busy) return;
    const version = ++selection.current;
    setLoadingHistory(true);
    setMobileNav(false);
    setError("");
    try {
      const [detail, trip] = await Promise.all([
        getJson<
          Conversation & {
            pending_choice?: PendingChoice | null;
            route_draft?: RouteDraft | null;
            last_run?: { trace?: TraceEvent[]; metrics?: Metrics };
            recent_messages: {
              id: number;
              role: "user" | "assistant";
              content: string;
            }[];
          }
        >(`/api/v1/conversations/${id}?message_limit=30`),
        fetch(`/api/v1/conversations/${id}/trip`).then(async (r) => {
          if (r.status === 404) return null;
          if (!r.ok) throw new Error("行程加载失败");
          return r.json();
        }),
      ]);
      if (version !== selection.current) return;
      setThread(id);
      remember(id);
      setMessages(
        detail.recent_messages.map((m) => ({ ...m, id: String(m.id) })),
      );
      setStatus(detail.status || "");
      setVisibleMessages(6);
      setInput("");
      setActiveNode("");
      if (trip?.plan_json?.itinerary) {
        const p = trip.plan_json;
        setSaved({
          markdown: trip.plan_md,
          version: trip.version,
          itinerary: p.itinerary,
          evidence: p.evidence || [],
          requirements: p.requirements || {},
          validation: p.validation || {},
        });
        setTrace(p.trace || []);
        setMetrics(p.metrics || {});
        setValidation(p.validation || {});
        setStatus(
          [...((p.trace || []) as TraceEvent[])]
            .reverse()
            .find((event) => event.stage === "deliver")?.status ||
            (p.validation?.passed ? "completed" : ""),
        );
        setShowingSavedRun(true);
      } else {
        setSaved(undefined);
        setTrace([]);
        setMetrics({});
        setValidation({});
        setShowingSavedRun(false);
      }
      setRouteDraft(detail.route_draft || undefined);
      setPendingChoice(detail.pending_choice || undefined);
      if (
        detail.pending_choice ||
        detail.route_draft ||
        !trip?.plan_json?.itinerary
      ) {
        setStatus(
          detail.pending_choice ? "awaiting_choice" : detail.status || "",
        );
        setTrace(detail.last_run?.trace || []);
        setMetrics(detail.last_run?.metrics || {});
        setValidation({});
        setShowingSavedRun(false);
      }
    } catch (err) {
      if (version === selection.current) setError((err as Error).message);
    } finally {
      if (version === selection.current) setLoadingHistory(false);
    }
  }

  async function submit(text = input, choiceSelection?: ChoiceSelection) {
    if (!text.trim() || busy || loadingHistory) return;
    const controller = new AbortController();
    abort.current = controller;
    pendingText.current = text;
    remember(thread);
    setInput("");
    setBusy(true);
    setError("");
    setTrace([]);
    setMetrics({});
    setValidation({});
    if (!choiceSelection) {
      setRouteDraft(undefined);
      setPendingChoice(undefined);
    }
    setStatus("planning");
    setShowingSavedRun(false);
    setActiveNode("understand");
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: text.trim() },
    ]);
    try {
      const data = await streamPlan(
        thread,
        text.trim(),
        controller.signal,
        (event) => {
          if (controller.signal.aborted) return;
          setTrace(event.trace);
          if (event.validation) setValidation(event.validation);
          if (event.metrics) setMetrics(event.metrics);
          if ("route_draft" in event)
            setRouteDraft(event.route_draft || undefined);
          const group: Record<string, string> = {
            route_research: "research",
            draft_geography: "draft_route",
            geography: "validate",
          };
          setActiveNode(
            event.phase === "complete" ? "" : group[event.node] || event.node,
          );
        },
        choiceSelection,
      );
      if (controller.signal.aborted) return;
      setTrace(data.trace);
      setMetrics(data.metrics);
      setValidation(data.validation);
      setStatus(data.status);
      setRouteDraft(data.route_draft || undefined);
      setPendingChoice(data.pending_choice || undefined);
      void getJson<{ status: string }>("/health")
        .then((result) => setHealth(result.status === "ok" ? "ok" : "degraded"))
        .catch(() => setHealth("offline"));
      setActiveNode("");
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: data.reply },
      ]);
      if (data.plan.plan_content && data.plan.itinerary) {
        setSaved({
          markdown: data.plan.plan_content,
          version: data.plan.version,
          itinerary: data.plan.itinerary,
          evidence: data.evidence,
          requirements: data.requirements,
          validation: data.validation,
        });
      }
      if (!data.persisted)
        setError("本轮结果未能保存，刷新后可能丢失。请检查数据库状态。");
      void refreshHistory();
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setStatus("failed");
        void getJson<{ status: string }>("/health")
          .then((result) =>
            setHealth(result.status === "ok" ? "ok" : "degraded"),
          )
          .catch(() => setHealth("offline"));
        setInput(text);
      }
    } finally {
      if (!controller.signal.aborted) {
        setBusy(false);
        setActiveNode("");
        inputRef.current?.focus();
      }
    }
  }

  function cancelExecution() {
    abort.current?.abort();
    setBusy(false);
    setActiveNode("");
    setStatus("failed");
    setInput(pendingText.current);
    setError("本轮已停止。之前保存的行程保留，你可以调整需求后重新发送。");
  }

  function selectOptions(choice: ChoiceSelection) {
    if (!pendingChoice) return;
    const categoryText = (category: "hotel" | "restaurant") => {
      const options =
        category === "hotel" ? pendingChoice.hotels : pendingChoice.restaurants;
      if (!options.length) return "";
      const mode =
        (category === "hotel" ? choice.hotel_mode : choice.restaurant_mode) ||
        "lock";
      const ids =
        category === "hotel"
          ? [choice.hotel_evidence_id]
          : choice.restaurant_evidence_ids || [];
      const names = options
        .filter((option) => ids.includes(option.evidence_id))
        .map((option) => option.name)
        .join("、");
      const label = category === "hotel" ? "住宿" : "餐饮";
      return mode === "automatic"
        ? `${label}交给 Agent 安排`
        : `${label}${mode === "prefer" ? "优先考虑" : "必须采用"}：${names}`;
    };
    void submit(
      choice.automatic
        ? "这些候选请交给 Agent 自动安排。"
        : `${[categoryText("hotel"), categoryText("restaurant")].filter(Boolean).join("；")}。请继续规划。`,
      choice,
    );
  }

  const examples = [
    {
      city: "杭州",
      en: "HANGZHOU",
      type: "湖山与人文",
      css: "hangzhou",
      prompt: `${dateAfter(7)}到${dateAfter(9)}去杭州，1个人，人均预算1500元。喜欢湖边散步和博物馆，节奏轻松一点。`,
    },
    {
      city: "苏州",
      en: "SUZHOU",
      type: "园林里的慢时光",
      css: "suzhou",
      prompt: `${dateAfter(7)}到${dateAfter(8)}去苏州，两个人，人均预算1200元，想逛古典园林、品尝本地菜。`,
    },
    {
      city: "成都",
      en: "CHENGDU",
      type: "烟火与松弛感",
      css: "chengdu",
      prompt: `${dateAfter(7)}到${dateAfter(9)}去成都，1个人，人均预算1800元，喜欢历史文化和川菜，行程不要太赶。`,
    },
  ];

  function download() {
    if (!saved) return;
    const url = URL.createObjectURL(
      new Blob([saved.markdown], { type: "text/markdown;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `${saved.itinerary.city}-旅行计划.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="app-shell">
      {mobileNav && (
        <div className="nav-scrim" onClick={() => setMobileNav(false)} />
      )}
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            reset();
          }}
        >
          <span className="brand-mark">
            <Compass size={25} />
          </span>
          <span>
            旅迹<span className="brand-en">VOYAGE / AI</span>
          </span>
        </a>
        <button className="new-trip" onClick={reset}>
          <Plus size={17} /> 开启新旅程 <span>NEW</span>
        </button>
        <div className="nav-label">工作空间</div>
        <div className="nav-current">
          <Route size={17} /> 旅行规划 <span className="tiny-dot" />
        </div>
        <div className="history-heading">
          <span className="nav-label">最近的旅程</span>
          <span>{history.length.toString().padStart(2, "0")}</span>
        </div>
        <nav className="history-list" aria-label="历史行程">
          {history.length === 0 ? (
            <p className="history-empty">
              每一段旅程，都从一个想法开始。
              <br />
              规划后会保存在这里。
            </p>
          ) : (
            history.map((c) => (
              <button
                key={c.thread_id}
                disabled={busy || loadingHistory}
                onClick={() => void openConversation(c.thread_id)}
                className={`history-item ${thread === c.thread_id ? "selected" : ""}`}
              >
                <MessageSquare size={15} />
                <span>
                  {c.city
                    ? `${c.city.replace(/市$/, "")}的旅行计划`
                    : "新的旅行灵感"}
                  <small>
                    {statusText[c.status || ""] || "对话中"} · {c.message_count}{" "}
                    条消息
                  </small>
                </span>
                <ChevronRight size={13} />
              </button>
            ))
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="project-badge">
            <span className="tiny-dot" /> LEARNING PROJECT
          </div>
          <p>
            让每一次出发
            <br />
            都有迹可循。
          </p>
          <button className="about-link" onClick={() => setShowAbout(true)}>
            <CircleHelp size={15} /> 关于这个项目 <ArrowUpRight size={14} />
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu icon-button"
              aria-label="打开导航"
              aria-expanded={mobileNav}
              onClick={() => setMobileNav(true)}
            >
              <Menu size={20} />
            </button>
            <Compass size={16} />
            <span>工作空间</span>
            <ChevronRight size={13} />
            <strong>旅行规划</strong>
          </div>
          <div className={`service-state ${health}`}>
            <span className="tiny-dot" />
            {health === "ok"
              ? "工具服务已连接"
              : health === "checking"
                ? "检查服务中"
                : health === "degraded"
                  ? "工具服务暂不可用"
                  : "后端未连接"}
          </div>
        </header>

        <div className={`workspace-body ${saved ? "has-plan" : ""}`}>
          <main className="main-column">
            {!saved && !routeDraft && (
              <section className="welcome">
                <div className="eyebrow">
                  <span /> A LITTLE CURIOSITY, A NEW JOURNEY
                </div>
                <h1>
                  下一站，
                  <br />
                  让好奇心<span>带路。</span>
                  <svg viewBox="0 0 120 20" aria-hidden="true">
                    <path d="M3 14Q55 1 116 8M22 18Q60 9 102 13" />
                  </svg>
                </h1>
                <p className="intro">
                  从一个想法，到一份周全的计划。
                  <br />和 AI 一起，找到属于你的旅行节奏。
                </p>
                <div className="destination-heading">
                  <span>从这里寻找灵感</span>
                  <span>
                    SELECT A STARTING POINT <ArrowUpRight size={13} />
                  </span>
                </div>
                <div className="destination-grid">
                  {examples.map((example, i) => (
                    <button
                      disabled={busy || loadingHistory}
                      key={example.city}
                      className={`destination ${example.css}`}
                      onClick={() => {
                        setInput(example.prompt);
                        inputRef.current?.focus();
                      }}
                    >
                      <CityArt kind={i} />
                      <span className="destination-number">0{i + 1}</span>
                      <div className="destination-caption">
                        <div>
                          <small>{example.en}</small>
                          <h3>
                            {example.city}
                            <span>{example.type}</span>
                          </h3>
                        </div>
                        <span className="destination-arrow">
                          <ArrowUpRight size={17} />
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {saved && (
              <section className="trip-overview">
                <div>
                  <div className="eyebrow">
                    <span /> YOUR NEXT CHAPTER
                  </div>
                  <h1>
                    {saved.itinerary.city.replace(/市$/, "")}
                    <span>，慢慢遇见。</span>
                  </h1>
                  <p>
                    <MapPin size={14} />
                    {saved.requirements.start_date} —{" "}
                    {saved.requirements.end_date}
                    <span className="separator">/</span>
                    {saved.itinerary.days.length} 天 ·{" "}
                    {saved.requirements.travelers || 1} 人
                  </p>
                </div>
                <button className="download-button" onClick={download}>
                  <Download size={15} /> 导出行程
                </button>
              </section>
            )}

            {messages.length > visibleMessages && (
              <button
                className="earlier-messages"
                onClick={() => setVisibleMessages((v) => v + 6)}
              >
                查看更早的对话（{messages.length - visibleMessages}）
              </button>
            )}
            <section
              className="conversation"
              aria-label="旅行对话"
              aria-live="polite"
            >
              {loadingHistory ? (
                <div className="loading-line">
                  <Loader2 size={16} className="spin" /> 正在打开这段旅程…
                </div>
              ) : (
                messages.slice(-visibleMessages).map((msg) => (
                  <div className={`message ${msg.role}`} key={msg.id}>
                    <div className="message-avatar">
                      {msg.role === "assistant" ? <Sparkles size={15} /> : "我"}
                    </div>
                    <div>
                      <span className="message-label">
                        {msg.role === "assistant" ? "旅迹助手" : "你的想法"}
                      </span>
                      <div className="message-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>
                ))
              )}
              {busy && (
                <div className="loading-line">
                  <span className="thinking-dots">
                    <i />
                    <i />
                    <i />
                  </span>
                  {stages.find((s) => s.key === activeNode)?.title ||
                    "正在完善你的计划"}
                  <button
                    className="cancel-execution"
                    onClick={cancelExecution}
                  >
                    停止本轮
                  </button>
                </div>
              )}
              <div ref={bottom} />
            </section>

            {error && (
              <div className="error-banner" role="alert">
                <CircleHelp size={17} />
                <span>{error}</span>
                <button aria-label="关闭提示" onClick={() => setError("")}>
                  <X size={15} />
                </button>
              </div>
            )}
            {routeDraft && (
              <div ref={draftRef}>
                <RouteDraftCard
                  draft={routeDraft}
                  interrupted={["failed", "blocked", "needs_revision"].includes(
                    status,
                  )}
                />
                {saved && (
                  <p className="choice-boundary">
                    以下为本轮草案。已保存的正式行程仍保留，只有新方案校验通过后才会替换。
                  </p>
                )}
              </div>
            )}
            {pendingChoice && (
              <div ref={choiceRef}>
                <section className="choice-panel">
                  <h3>先把行程安排好。</h3>
                  <p>
                    不必先挑酒店和餐厅，完成规划后可在各地点浏览。已明确指定的要求会继续保留。
                  </p>
                  <div className="choice-actions">
                    <button
                      className="choice-continue"
                      disabled={busy || loadingHistory}
                      onClick={() =>
                        void submit(
                          "请保留目的地、日期和明确指定要求，继续完成行程，未指定的食宿稍后再浏览。",
                        )
                      }
                    >
                      继续完成行程
                    </button>
                  </div>
                </section>
                <details>
                  <summary>查看已有候选（可选）</summary>
                  <ChoicePanel
                    key={pendingChoice.token}
                    pending={pendingChoice}
                    busy={busy || loadingHistory}
                    onSelect={selectOptions}
                    onAdjust={() => {
                      setInput("希望保留当前住宿和餐饮，但把游玩范围调整为：");
                      inputRef.current?.focus();
                    }}
                    onRefresh={() =>
                      void submit(
                        "请更新住宿和餐饮候选，保留目的地和日期，重新让我选择。",
                      )
                    }
                  />
                </details>
              </div>
            )}
            {!pendingChoice &&
              ["blocked", "needs_revision", "failed"].includes(status) && (
                <div className="recovery-actions">
                  <p>这轮没有生成通过校验的行程，可以调整后继续。</p>
                  <button
                    disabled={busy || loadingHistory}
                    onClick={() =>
                      void submit(
                        "请根据上轮具体冲突修正活动顺序和时间留白，保留日期及明确指定地点，继续完成行程；未指定食宿稍后再浏览。",
                      )
                    }
                  >
                    按冲突调整路线
                  </button>
                  <button
                    disabled={busy || loadingHistory}
                    onClick={() => {
                      setInput("关于上轮冲突，我想补充交通方式和游玩范围：");
                      inputRef.current?.focus();
                    }}
                  >
                    调整游玩范围
                  </button>
                </div>
              )}
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                maxLength={4000}
                rows={3}
                aria-label="旅行需求"
                placeholder={
                  saved
                    ? "想调整哪里？比如：第二天轻松一点，酒店换到市中心…"
                    : "我想去…  什么时候出发，有哪些期待？"
                }
                disabled={busy || loadingHistory}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void submit();
                  }
                }}
              />
              <div className="composer-bottom">
                <span>
                  <Sparkles size={14} />
                  {saved
                    ? "沿用当前旅程，继续完善"
                    : "目的地 · 日期 · 预算 · 你的偏好"}
                </span>
                <button
                  aria-label="发送旅行需求"
                  disabled={!input.trim() || busy || loadingHistory}
                >
                  {busy ? (
                    <Loader2 size={18} className="spin" />
                  ) : (
                    <ArrowUp size={19} />
                  )}
                </button>
              </div>
            </form>
            <div className="composer-note">
              <ShieldCheck size={12} />{" "}
              地点有来源，计划有校验。费用为估算，预订前请核实。
              <span>⌘ / Ctrl + Enter 发送</span>
            </div>

            {saved && (
              <TravelPlan
                saved={saved}
                threadId={thread}
                busy={busy}
                key={`${thread}:${saved.version || saved.markdown}`}
              />
            )}
            <footer className="page-footer">
              <span>VOYAGE / AI</span>
              <span>旅程值得期待，计划值得推敲。</span>
              <Globe2 size={14} />
            </footer>
          </main>

          <AgentInspector
            busy={busy}
            activeNode={activeNode}
            trace={trace}
            metrics={metrics}
            validation={validation}
            status={status}
            showingSavedRun={showingSavedRun}
          />
        </div>
      </div>
      {showAbout && (
        <div className="modal-backdrop" onClick={() => setShowAbout(false)}>
          <section
            className="about-modal"
            role="dialog"
            aria-modal="true"
            aria-label="关于旅迹"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="关闭"
              onClick={() => setShowAbout(false)}
            >
              <X size={20} />
            </button>
            <Compass size={32} />
            <h2>旅迹 · Voyage AI</h2>
            <p>一个用于学习与展示的旅行规划 Agent 项目。</p>
            <p>
              LangGraph
              编排需求理解、工具检索、结构化规划和程序校验。校验失败会携带反馈重新规划，达到修正上限后如实说明问题。
            </p>
            <p>
              地点信息来自高德
              MCP；日期、时间冲突、地点引用和预算由程序检查。费用为估算，尚未接入实时票价、房态、营业时间与导航服务。
            </p>
            <p>
              当前支持国内单城市、1–14 天行程。会话按轮次持久化到
              SQLite，适合本地单进程演示。
            </p>
            <div className="modal-stack">
              React · FastAPI · LangGraph · MCP · SQLite
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
