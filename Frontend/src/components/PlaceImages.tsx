import { useEffect, useMemo, useRef, useState } from "react";
import { ImageOff } from "lucide-react";
import type { Evidence } from "../types";

function imageUrls(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  const urls = values.flatMap((value) => {
    const raw = typeof value === "string" ? value : value?.url;
    if (typeof raw !== "string") return [];
    try {
      const url = new URL(raw);
      return ["http:", "https:"].includes(url.protocol) &&
        !url.username &&
        !url.password
        ? [url.href]
        : [];
    } catch {
      return [];
    }
  });
  return [...new Set(urls)].slice(0, 2);
}

function Photo({ url, name }: { url: string; name: string }) {
  const [failed, setFailed] = useState(false);
  return failed ? (
    <span className="place-image-placeholder">
      <ImageOff size={19} /> 图片暂不可用
    </span>
  ) : (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      aria-label={`查看${name}图片`}
    >
      <img
        src={url}
        alt={`${name} · 来源提供的地点图片`}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </a>
  );
}

export default function PlaceImages({
  place,
  threadId,
  version,
  busy,
}: {
  place: Evidence;
  threadId: string;
  version?: string;
  busy: boolean;
}) {
  const initial = useMemo(
    () => imageUrls(place.data.image_urls),
    [place.data.image_urls],
  );
  const [urls, setUrls] = useState(initial);
  const [status, setStatus] = useState<
    "loading" | "ok" | "empty" | "unavailable"
  >(initial.length ? "ok" : version ? "loading" : "empty");
  const [visible, setVisible] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const container = useRef<HTMLElement>(null);
  const completed = useRef(false);

  useEffect(() => {
    if (initial.length || !container.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [initial.length]);

  useEffect(() => {
    if (initial.length || !version || !visible || busy || completed.current)
      return;
    const controller = new AbortController();
    setStatus("loading");
    (async () => {
      try {
        const response = await fetch(
          `/api/v1/conversations/${encodeURIComponent(threadId)}/place-images`,
          {
            method: "POST",
            signal: controller.signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              plan_version: version,
              evidence_id: place.evidence_id,
            }),
          },
        );
        if (!response.ok) throw new Error("图片暂不可用");
        const result = await response.json();
        if (
          result.plan_version !== version ||
          result.evidence_id !== place.evidence_id
        )
          throw new Error("地点已更新");
        if (!controller.signal.aborted) {
          completed.current = true;
          const images = imageUrls(result.images);
          setUrls(images);
          setStatus(
            images.length
              ? "ok"
              : result.status === "unavailable"
                ? "unavailable"
                : "empty",
          );
        }
      } catch {
        if (!controller.signal.aborted) {
          completed.current = true;
          setStatus("unavailable");
        }
      }
    })();
    return () => controller.abort();
  }, [
    initial.length,
    version,
    visible,
    busy,
    threadId,
    place.evidence_id,
    attempt,
  ]);

  const name = place.data.name || "该地点";
  return (
    <section
      className="place-images"
      ref={container}
      aria-label={`${name}图片`}
    >
      <div className={`place-images-grid${urls.length < 2 ? " single" : ""}`}>
        {urls.length ? (
          urls.map((url) => <Photo key={url} url={url} name={name} />)
        ) : (
          <span className="place-image-placeholder" role="status">
            <ImageOff size={19} />
            {status === "loading"
              ? "正在加载地点图片…"
              : status === "unavailable"
                ? "地点图片暂不可用"
                : "来源暂未提供地点图片"}
          </span>
        )}
      </div>
      {(urls.length > 0 || status === "unavailable") && (
        <small className="place-image-source">
          {urls.length > 0 && `图片来源：${place.source} · 点击图片查看大图`}
          {status === "unavailable" && (
            <button
              type="button"
              onClick={() => {
                completed.current = false;
                setAttempt((value) => value + 1);
              }}
              disabled={busy}
            >
              重试图片
            </button>
          )}
        </small>
      )}
    </section>
  );
}
