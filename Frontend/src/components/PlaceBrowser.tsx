import { useEffect, useRef, useState } from "react";
import { ExternalLink, ImageOff, Loader2, X } from "lucide-react";
import type { BrowseContext, BrowseResult } from "../types";

function PlacePhoto({
  images,
  name,
}: {
  images: BrowseResult["items"][number]["images"];
  name: string;
}) {
  const [index, setIndex] = useState(0);
  return images[index] ? (
    <img
      className="browse-photo"
      src={images[index].url}
      alt={`${name} · 来源提供的图片`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setIndex((value) => value + 1)}
    />
  ) : (
    <div className="browse-photo placeholder">
      <ImageOff size={23} />
      <span>{images.length ? "图片暂不可用" : "来源暂未提供图片"}</span>
    </div>
  );
}

export default function PlaceBrowser({
  id,
  threadId,
  version,
  context,
  onClose,
}: {
  id?: string;
  threadId: string;
  version: string;
  context: BrowseContext;
  onClose: () => void;
}) {
  const [result, setResult] = useState<BrowseResult>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const sequence = useRef(0);
  useEffect(() => {
    const current = ++sequence.current;
    const controller = new AbortController();
    setResult(undefined);
    setError("");
    (async () => {
      try {
        const response = await fetch(
          `/api/v1/conversations/${encodeURIComponent(threadId)}/browse`,
          {
            method: "POST",
            signal: controller.signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              plan_version: version,
              date: context.date,
              anchor_evidence_id: context.anchorId,
              category: context.category,
            }),
          },
        );
        const data = await response.json();
        if (!response.ok)
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : "浏览暂时不可用，请稍后重试。",
          );
        if (!controller.signal.aborted && current === sequence.current)
          setResult(data);
      } catch (err) {
        if (!controller.signal.aborted && current === sequence.current)
          setError((err as Error).message);
      }
    })();
    return () => {
      controller.abort();
      sequence.current += 1;
    };
  }, [
    threadId,
    version,
    context.date,
    context.anchorId,
    context.category,
    attempt,
  ]);
  return (
    <section
      id={id}
      className="place-browser"
      role="region"
      aria-label={context.category === "hotel" ? "浏览酒店" : "浏览特色美食"}
    >
      <div className="browse-heading">
        <div>
          <span className="eyebrow">EXPLORE AT YOUR PACE</span>
          <h3>
            {context.category === "hotel"
              ? "为这一晚找个落脚点"
              : "在这里，发现当地味道"}
          </h3>
          <p>
            {context.date} · {context.anchorName} 周边
          </p>
        </div>
        <button onClick={onClose} aria-label="关闭浏览">
          <X size={20} />
        </button>
      </div>
      {!result && !error && (
        <p role="status" className="loading-line">
          <Loader2 className="spin" size={17} />{" "}
          正在按这个地点检索，原行程可继续阅读…
        </p>
      )}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button onClick={() => setAttempt((value) => value + 1)}>
            重试浏览
          </button>
        </div>
      )}
      {result && (
        <>
          <p className="choice-boundary">{result.relation}</p>
          {!result.items.length && (
            <p role="status">
              这个地点暂未找到匹配候选。可换一个活动地点浏览，原行程不受影响。
            </p>
          )}
          <div className="browse-grid">
            {result.items.map((item) => (
              <article className="browse-card" key={item.poi_id}>
                <PlacePhoto
                  key={`${item.poi_id}:${item.images.map((image) => image.url).join()}`}
                  images={item.images}
                  name={item.name}
                />
                <div>
                  <h4>{item.name}</h4>
                  <p>{item.address || "地址待确认"}</p>
                  {item.distance_km !== null && (
                    <p>距参照点直线约 {item.distance_km} km · 非导航</p>
                  )}
                  <small>
                    {item.source} ·{" "}
                    {new Date(item.fetched_at).toLocaleString("zh-CN")}
                    {item.images.length ? " · 图片由同一地点来源提供" : ""}
                  </small>
                  <a
                    href={`https://uri.amap.com/search?keyword=${encodeURIComponent(item.name)}&city=${encodeURIComponent(result.city)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    在地图中查看 <ExternalLink size={12} />
                  </a>
                </div>
              </article>
            ))}
          </div>
          <p className="choice-boundary">
            {result.notice} 浏览不会加入行程或锁定偏好。
          </p>
        </>
      )}
    </section>
  );
}
