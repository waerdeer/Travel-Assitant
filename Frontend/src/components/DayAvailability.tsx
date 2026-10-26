import type { Requirements } from "../types";

function timeMinutes(value?: string | null): number | undefined {
  if (!value || !/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return;
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function buffer(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.min(360, value))
    : fallback;
}

function clock(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

export function getDayAvailability(
  requirements: Requirements | undefined,
  date: string,
  firstDate: string,
  lastDate: string,
) {
  const req = requirements || {};
  const arrivalTime = timeMinutes(req.arrival_time);
  const departureTime = timeMinutes(req.departure_time);
  const arrivalBuffer = buffer(req.arrival_buffer_minutes, 60);
  const departureBuffer = buffer(req.departure_buffer_minutes, 90);
  const offset = (boundary: string) =>
    ((Date.parse(`${boundary}T00:00:00Z`) - Date.parse(`${date}T00:00:00Z`)) /
      86400000) *
    1440;
  const start = Math.max(
    480,
    arrivalTime === undefined
      ? 480
      : arrivalTime + arrivalBuffer + offset(firstDate),
  );
  const end = Math.min(
    1260,
    departureTime === undefined
      ? 1260
      : departureTime - departureBuffer + offset(lastDate),
  );
  const arrival = date === firstDate || start > 480 ? arrivalTime : undefined;
  const departure = date === lastDate || end < 1260 ? departureTime : undefined;
  const rest = req.rest_dates?.includes(date) || false;
  const allowEmpty =
    rest ||
    ((arrival !== undefined || departure !== undefined) && end - start < 180);
  const emptyMessage = rest
    ? "这天按你的要求休息，不安排景点。"
    : allowEmpty && arrival !== undefined && departure !== undefined
      ? "这天以抵达、接驳与返程为主，不安排景点。"
      : allowEmpty && arrival !== undefined
        ? "抵达后以接驳、入住和休息为主，不安排景点。"
        : allowEmpty && departure !== undefined
          ? "这天为离城接驳和返程留白，不安排景点。"
          : "当天尚未安排景点，请核对休息或交通安排。";
  return {
    arrival,
    departure,
    arrivalBuffer,
    departureBuffer,
    rest,
    allowEmpty,
    hasWindow: end > start,
    window: end > start ? `${clock(start)}–${clock(end)}` : "",
    constrained: rest || arrival !== undefined || departure !== undefined,
    emptyMessage,
  };
}

export default function DayAvailability({
  requirements,
  date,
  firstDate,
  lastDate,
  empty,
}: {
  requirements?: Requirements;
  date: string;
  firstDate: string;
  lastDate: string;
  empty: boolean;
}) {
  const day = getDayAvailability(requirements, date, firstDate, lastDate);
  if (!day.constrained && !empty) return null;
  return (
    <section className="day-availability" aria-label={`${date}活动时段`}>
      <strong>
        {day.rest
          ? "休息日"
          : day.hasWindow
            ? `可安排活动：${day.window}`
            : "本日不安排观光"}
      </strong>
      {day.arrival !== undefined && (
        <p>
          {date !== firstDate && `${firstDate} `}
          {requirements?.arrival_time} 抵达城市，预留 {day.arrivalBuffer}{" "}
          分钟接驳与安顿。
        </p>
      )}
      {day.departure !== undefined && (
        <p>
          {date !== lastDate && `${lastDate} `}
          {requirements?.departure_time} 离开城市，提前 {day.departureBuffer}{" "}
          分钟准备返程。
        </p>
      )}
      {(day.arrival !== undefined || day.departure !== undefined) && (
        <small>接驳留白为规划假设，实际交通请另行核实。</small>
      )}
      {empty && <p className="empty-day-note">{day.emptyMessage}</p>}
    </section>
  );
}
