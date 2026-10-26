import { useState } from "react";
import { Check, ExternalLink, Users } from "lucide-react";
import type {
  ChoiceMode,
  ChoiceOption,
  ChoiceSelection,
  PendingChoice,
} from "../types";

interface Props {
  pending: PendingChoice;
  busy: boolean;
  onSelect: (selection: ChoiceSelection) => void;
  onRefresh: () => void;
  onAdjust: () => void;
}

export default function ChoicePanel({
  pending,
  busy,
  onSelect,
  onRefresh,
  onAdjust,
}: Props) {
  const modern = pending.selection_policy === "prefer_or_lock";
  const initialMode = (
    key: "hotel_evidence_id" | "restaurant_evidence_ids",
  ): ChoiceMode =>
    pending.selected_options[key] ? "lock" : modern ? "prefer" : "lock";
  const [hotelMode, setHotelMode] = useState<ChoiceMode>(
    initialMode("hotel_evidence_id"),
  );
  const [foodMode, setFoodMode] = useState<ChoiceMode>(
    initialMode("restaurant_evidence_ids"),
  );
  const initial = { ...pending.preferred_options, ...pending.selected_options };
  const [hotel, setHotel] = useState(
    pending.hotels.some((h) => h.evidence_id === initial.hotel_evidence_id)
      ? initial.hotel_evidence_id || ""
      : "",
  );
  const [food, setFood] = useState<string[]>(
    (initial.restaurant_evidence_ids || []).filter((id) =>
      pending.restaurants.some((r) => r.evidence_id === id),
    ),
  );
  const valid =
    (!pending.hotels.length || hotelMode === "automatic" || !!hotel) &&
    (!pending.restaurants.length ||
      foodMode === "automatic" ||
      food.length > 0);
  const unchangedBlocked =
    pending.no_progress &&
    hotelMode === initialMode("hotel_evidence_id") &&
    foodMode === initialMode("restaurant_evidence_ids") &&
    (!pending.hotels.length || hotel === initial.hotel_evidence_id) &&
    (!pending.restaurants.length ||
      JSON.stringify([...food].sort()) ===
        JSON.stringify([...(initial.restaurant_evidence_ids || [])].sort()));
  function modePicker(category: "hotel" | "restaurant") {
    const mode = category === "hotel" ? hotelMode : foodMode;
    const update = category === "hotel" ? setHotelMode : setFoodMode;
    return (
      modern && (
        <label className="choice-mode">
          采用方式
          <select
            aria-label={category === "hotel" ? "住宿采用方式" : "餐饮采用方式"}
            value={mode}
            onChange={(event) => update(event.target.value as ChoiceMode)}
          >
            <option value="prefer">优先考虑 · 允许按路线调整</option>
            <option value="lock">必须采用 · 冲突时重新确认</option>
            <option value="automatic">交给 Agent 安排</option>
          </select>
        </label>
      )
    );
  }
  function card(option: ChoiceOption, category: "hotel" | "restaurant") {
    const selected =
      category === "hotel"
        ? hotel === option.evidence_id
        : food.includes(option.evidence_id);
    return (
      <div
        className={`choice-card ${selected ? "selected" : ""}`}
        key={option.evidence_id}
      >
        <label>
          <input
            type={category === "hotel" ? "radio" : "checkbox"}
            name={category === "hotel" ? "hotel-choice" : option.evidence_id}
            checked={selected}
            disabled={
              busy ||
              (category === "hotel" ? hotelMode : foodMode) === "automatic" ||
              (category === "restaurant" && !selected && food.length >= 3)
            }
            onChange={() =>
              category === "hotel"
                ? setHotel(option.evidence_id)
                : setFood((current) =>
                    selected
                      ? current.filter((id) => id !== option.evidence_id)
                      : [...current, option.evidence_id],
                  )
            }
          />
          <span>
            <strong>{option.name}</strong>
            <span className="choice-address">
              {option.address || "地址未提供"}
            </span>
          </span>
        </label>
        {option.retrieval_hint && (
          <span className="choice-angle">
            检索方向 · {option.retrieval_hint}
          </span>
        )}
        {option.route_relation && (
          <span className="choice-angle">{option.route_relation}</span>
        )}
        <a
          href={`https://uri.amap.com/search?keyword=${encodeURIComponent(option.name)}&city=${encodeURIComponent(pending.city)}`}
          target="_blank"
          rel="noreferrer"
        >
          地图信息 <ExternalLink size={11} />
        </a>
      </div>
    );
  }
  return (
    <section className="choice-panel" aria-label="选择住宿与餐饮">
      <div className="choice-title">
        <Users size={19} />
        <span>让计划，更合你的心意。</span>
        <span className="choice-pause">{busy ? "处理中" : "等你选择"}</span>
      </div>
      {pending.trip_summary && (
        <p className="choice-trip">{pending.trip_summary}</p>
      )}
      <p>{pending.message}</p>
      {pending.draft_id && (
        <a className="draft-link" href="#route-draft">
          查看本轮路线草案 ↑
        </a>
      )}
      {!!pending.hotels.length && (
        <fieldset disabled={busy}>
          <legend>
            住宿候选 <span>选 1 家 · {pending.hotels.length} 个不同候选</span>
          </legend>
          {modePicker("hotel")}
          <div className="choice-grid">
            {pending.hotels.map((h) => card(h, "hotel"))}
          </div>
        </fieldset>
      )}
      {!!pending.restaurants.length && (
        <fieldset disabled={busy}>
          <legend>
            餐饮候选 <span>选 1–3 家 · 已选 {food.length} 家</span>
          </legend>
          {modePicker("restaurant")}
          <p>
            {foodMode === "lock"
              ? "必须采用：全程只从选中的餐厅安排用餐；这不是单餐预订。"
              : foodMode === "prefer"
                ? "优先考虑：将尽量安排所选餐厅，允许根据每日路线补充或调整。"
                : "由 Agent 按每天路线安排餐饮。"}
          </p>
          <div className="choice-grid">
            {pending.restaurants.map((r) => card(r, "restaurant"))}
          </div>
        </fieldset>
      )}
      <p className="choice-boundary">
        候选来自地图检索。检索方向不代表已核实的等级或菜系；价格、营业时间和房态待确认，尚未预订。若选择与路线冲突，会说明原因并重新征求你的选择。
      </p>
      <div className="choice-actions">
        <button
          disabled={busy || !valid || !!unchangedBlocked}
          className="choice-continue"
          onClick={() =>
            onSelect({
              token: pending.token,
              hotel_evidence_id:
                hotelMode === "automatic" ? null : hotel || null,
              hotel_mode: hotelMode,
              restaurant_mode: foodMode,
              restaurant_evidence_ids: foodMode === "automatic" ? [] : food,
            })
          }
        >
          <Check size={15} />
          按我的选择继续
        </button>
        <button
          disabled={busy || !!pending.automatic_retry_blocked}
          onClick={() => onSelect({ token: pending.token, automatic: true })}
        >
          交给 Agent 自动安排
        </button>
        <button disabled={busy} onClick={onRefresh}>
          换一批候选
        </button>
        {pending.no_progress && (
          <button disabled={busy} onClick={onAdjust}>
            调整游玩范围
          </button>
        )}
      </div>
      {unchangedBlocked && (
        <p role="status">
          相同选择仍有路线冲突，继续按钮暂不可用。请换选、调整范围或主动重查。
        </p>
      )}
      <small>
        {busy
          ? "正在处理本轮请求，选项暂时锁定。"
          : "候选与等待状态已随会话保存，可以稍后回来继续。等待期间不会继续调用模型。"}
      </small>
    </section>
  );
}
