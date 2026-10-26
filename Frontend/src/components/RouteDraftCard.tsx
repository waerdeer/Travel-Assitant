import { MapPin, Route } from "lucide-react";
import type { RouteDraft } from "../types";
import DayAvailability from "./DayAvailability";

export default function RouteDraftCard({
  draft,
  interrupted,
}: {
  draft: RouteDraft;
  interrupted: boolean;
}) {
  const lookup = new Map(draft.evidence.map((e) => [e.evidence_id, e]));
  return (
    <section className="route-draft" id="route-draft" aria-label="路线草案">
      <div className="choice-title">
        <Route size={19} />
        <span>{draft.city} · 路线草案</span>
        <span className="choice-pause">尚未定稿</span>
      </div>
      <p className="draft-rationale">{draft.rationale}</p>
      {interrupted && (
        <p role="status">
          本轮未完成，以下仅保留已形成的草案，不能作为正式出行计划。
        </p>
      )}
      <div className="draft-days">
        {draft.days.map((day, i) => (
          <article key={day.date}>
            <span className="draft-date">
              DAY {String(i + 1).padStart(2, "0")} · {day.date}
            </span>
            <h3>{day.theme}</h3>
            <DayAvailability
              requirements={draft.requirements}
              date={day.date}
              firstDate={draft.days[0].date}
              lastDate={draft.days[draft.days.length - 1].date}
              empty={day.attraction_evidence_ids.length === 0}
            />
            {day.attraction_evidence_ids.map((id) => {
              const item = lookup.get(id);
              return (
                <div className="draft-place" key={id}>
                  <MapPin size={14} />
                  <div>
                    <a
                      href={`https://uri.amap.com/search?keyword=${encodeURIComponent(item?.data.name || "")}&city=${encodeURIComponent(draft.city)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item?.data.name || "地点证据缺失"}
                    </a>
                    <small>{item?.data.address || "地址待确认"}</small>
                    <small>
                      {item?.source || "来源待确认"} ·{" "}
                      {item?.fetched_at
                        ? new Date(item.fetched_at).toLocaleString("zh-CN")
                        : "检索时间未知"}
                    </small>
                  </div>
                </div>
              );
            })}
          </article>
        ))}
      </div>
      {draft.warnings.map((warning) => (
        <p className="draft-warning" key={warning}>
          {warning}
        </p>
      ))}
      <p className="choice-boundary">
        草案已检查：{draft.checked.join("、")}。待完善：
        {draft.unchecked.join("、")}
        。接下来按主要活动补充食宿，最终安排仍需校验。
      </p>
    </section>
  );
}
