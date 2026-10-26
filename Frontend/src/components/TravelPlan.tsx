import { useState } from "react";
import {
  Route,
  FileText,
  Check,
  Leaf,
  ExternalLink,
  MapPin,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import InlinePlaceBrowser from "./InlinePlaceBrowser";
import PlaceImages from "./PlaceImages";
import DayAvailability from "./DayAvailability";
import type { SavedPlan } from "../types";
export default function TravelPlan({
  saved,
  threadId,
  busy,
}: {
  saved: SavedPlan;
  threadId: string;
  busy: boolean;
}) {
  const [tab, setTab] = useState<"itinerary" | "document">("itinerary");
  const usedEvidence = new Map(saved.evidence.map((e) => [e.evidence_id, e]));
  const totalCost =
    saved.itinerary.costs.accommodation +
    saved.itinerary.costs.meals +
    saved.itinerary.costs.transport +
    saved.itinerary.costs.tickets;
  return (
    <section className="plan-section">
      <div className="plan-toolbar">
        <div className="plan-tabs">
          <button
            className={tab === "itinerary" ? "active" : ""}
            onClick={() => setTab("itinerary")}
          >
            <Route size={15} /> 每日行程
          </button>
          <button
            className={tab === "document" ? "active" : ""}
            onClick={() => setTab("document")}
          >
            <FileText size={15} /> 完整计划
          </button>
        </div>
        <span className="verified-label">
          <Check size={13} />{" "}
          {saved.validation.unverified_checks === undefined
            ? "旧版行程 · 建议重新检查"
            : "已保存的校验通过版本"}
        </span>
      </div>
      {tab === "document" ? (
        <article className="markdown-document">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {saved.markdown}
          </ReactMarkdown>
        </article>
      ) : (
        <>
          <div className="trip-stats">
            <div>
              <span>旅行时长</span>
              <strong>
                {saved.itinerary.days.length}
                <small> 天</small>
              </strong>
            </div>
            <div>
              <span>人均费用估算</span>
              <strong>
                <small>¥ </small>
                {totalCost.toLocaleString()}
              </strong>
            </div>
            <div>
              <span>有来源的地点</span>
              <strong>
                {
                  new Set(
                    [
                      ...saved.itinerary.days.flatMap((d) =>
                        d.stops.map((s) => s.evidence_id),
                      ),
                      saved.itinerary.hotel_evidence_id,
                    ].filter(Boolean),
                  ).size
                }
                <small> 处</small>
              </strong>
            </div>
          </div>
          {saved.itinerary.days.map((day, index) => (
            <article className="day-card" key={day.date}>
              <div className="day-heading">
                <span className="day-number">
                  DAY {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <h2>{day.theme}</h2>
                  <span>{day.date}</span>
                </div>
                <Leaf size={18} />
              </div>
              <DayAvailability
                requirements={saved.requirements}
                date={day.date}
                firstDate={saved.itinerary.days[0].date}
                lastDate={
                  saved.itinerary.days[saved.itinerary.days.length - 1].date
                }
                empty={
                  !day.stops.some(
                    (stop) =>
                      usedEvidence.get(stop.evidence_id)?.category ===
                      "attraction",
                  )
                }
              />
              <div className="stop-list">
                {[
                  ...day.stops.map((stop) => ({ ...stop, flexible: false })),
                  ...(day.meal_breaks || []).map((meal) => ({
                    ...meal,
                    evidence_id: meal.anchor_evidence_id,
                    flexible: true,
                    note: "自由用餐留白 · 尚未指定餐厅，可按需浏览周边美食",
                  })),
                ]
                  .sort((a, b) => a.start_time.localeCompare(b.start_time))
                  .map((stop, i) => {
                    const place = usedEvidence.get(stop.evidence_id);
                    return (
                      <div className="stop" key={`${stop.evidence_id}-${i}`}>
                        <div className="stop-time">
                          {stop.start_time}
                          <small>{stop.end_time}</small>
                        </div>
                        <div className="stop-dot">
                          <span />
                        </div>
                        <div className="stop-detail">
                          <div>
                            <h3>
                              {stop.flexible
                                ? `自由用餐 · ${place?.data.name || "活动地点"}周边`
                                : place?.data.name || "地点信息缺失"}
                            </h3>
                            <span className="place-tag">
                              {stop.flexible
                                ? "灵活安排"
                                : place?.category === "restaurant"
                                  ? "当地美食"
                                  : "探索与体验"}
                            </span>
                          </div>
                          <p>{place?.data.address}</p>
                          {stop.note && (
                            <p className="stop-note">{stop.note}</p>
                          )}
                          {!stop.flexible && place && (
                            <PlaceImages
                              key={`${threadId}:${saved.version}:${place.evidence_id}`}
                              place={place}
                              threadId={threadId}
                              version={saved.version}
                              busy={busy}
                            />
                          )}
                          <a
                            href={`https://uri.amap.com/search?keyword=${encodeURIComponent(place?.data.name || "")}&city=${encodeURIComponent(saved.itinerary.city)}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            在高德查看 <ExternalLink size={11} />
                          </a>
                          {!stop.flexible &&
                            place?.category === "attraction" && (
                              <InlinePlaceBrowser
                                threadId={threadId}
                                version={saved.version}
                                busy={busy}
                                context={{
                                  date: day.date,
                                  anchorId: place.evidence_id,
                                  anchorName: place.data.name || "活动地点",
                                  category: "restaurant",
                                }}
                              />
                            )}
                        </div>
                      </div>
                    );
                  })}
              </div>
              {index < saved.itinerary.days.length - 1 &&
                (() => {
                  const anchor = usedEvidence.get(
                    saved.itinerary.hotel_evidence_id ||
                      day.stay_anchor_evidence_id ||
                      day.stops.find(
                        (stop) =>
                          usedEvidence.get(stop.evidence_id)?.category ===
                          "attraction",
                      )?.evidence_id ||
                      "",
                  );
                  return anchor ? (
                    <div className="daily-stay">
                      <MapPin size={18} />
                      <div className="stay-detail">
                        <span className="eyebrow">REST FOR THE NEXT DAY</span>
                        <h3>
                          {saved.itinerary.hotel_evidence_id
                            ? `住宿参考 · ${anchor.data.name}`
                            : `住宿建议区域 · ${anchor.data.name}周边`}
                        </h3>
                        <p>
                          {saved.itinerary.hotel_evidence_id
                            ? "保留当前住宿参考，未进行预订。"
                            : "以当天活动地点为检索参照，具体酒店与往返交通待确认。"}
                        </p>
                      </div>
                      <InlinePlaceBrowser
                        threadId={threadId}
                        version={saved.version}
                        busy={busy}
                        context={{
                          date: day.date,
                          anchorId: anchor.evidence_id,
                          anchorName: anchor.data.name || "住宿区域",
                          category: "hotel",
                        }}
                      />
                    </div>
                  ) : (
                    <div className="daily-stay">
                      <MapPin size={18} />
                      <div className="stay-detail">
                        <h3>住宿区域待定</h3>
                        <p>
                          当天暂无可用的住宿参照点，可在对话中补充住宿位置。
                        </p>
                      </div>
                    </div>
                  );
                })()}
            </article>
          ))}
          {saved.itinerary.hotel_evidence_id && (
            <div className="hotel-card">
              <MapPin size={20} />
              <div>
                <span className="eyebrow">STAY A LITTLE LONGER</span>
                <h3>
                  {
                    usedEvidence.get(saved.itinerary.hotel_evidence_id)?.data
                      .name
                  }
                </h3>
                <p>
                  {
                    usedEvidence.get(saved.itinerary.hotel_evidence_id)?.data
                      .address
                  }
                </p>
                <small>地图检索候选 · 房价与房态待核实 · 未进行预订</small>
                {usedEvidence.get(saved.itinerary.hotel_evidence_id) && (
                  <PlaceImages
                    key={`${threadId}:${saved.version}:${saved.itinerary.hotel_evidence_id}`}
                    place={usedEvidence.get(saved.itinerary.hotel_evidence_id)!}
                    threadId={threadId}
                    version={saved.version}
                    busy={busy}
                  />
                )}
              </div>
            </div>
          )}
          <div className="cost-card">
            <h3>把预算，也安排妥当。</h3>
            <div className="cost-grid">
              {(
                [
                  ["住宿", "accommodation"],
                  ["餐饮", "meals"],
                  ["市内交通", "transport"],
                  ["门票", "tickets"],
                ] as const
              ).map(([label, key]) => (
                <div key={key}>
                  <span>{label}</span>
                  <strong>¥{saved.itinerary.costs[key]}</strong>
                </div>
              ))}
            </div>
            <p>{saved.itinerary.costs.basis}</p>
            <small>全程人均估算，不含往返目的地大交通，不代表实时报价。</small>
          </div>
        </>
      )}
    </section>
  );
}
