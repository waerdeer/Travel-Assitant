export interface Requirements {
  city?: string;
  start_date?: string;
  end_date?: string;
  budget_per_person?: number | null;
  travelers?: number;
  preferences?: string;
  pace?: string;
  must_visit?: string[];
  arrival_time?: string | null;
  departure_time?: string | null;
  arrival_buffer_minutes?: number;
  departure_buffer_minutes?: number;
  rest_dates?: string[];
}
export interface Evidence {
  evidence_id: string;
  category: string;
  source: string;
  fetched_at: string;
  city: string;
  data: {
    name?: string;
    address?: string;
    location?: string;
    date?: string;
    dayweather?: string;
    daytemp?: string;
    [key: string]: unknown;
  };
}
export interface Stop {
  evidence_id: string;
  start_time: string;
  end_time: string;
  note?: string;
}
export interface Itinerary {
  service_mode?: "specific" | "browse";
  city: string;
  days: {
    date: string;
    theme: string;
    stops: Stop[];
    stay_anchor_evidence_id?: string | null;
    meal_breaks?: {
      anchor_evidence_id: string;
      start_time: string;
      end_time: string;
    }[];
  }[];
  hotel_evidence_id?: string;
  suggestions: string[];
  costs: {
    accommodation: number;
    meals: number;
    transport: number;
    tickets: number;
    basis: string;
  };
}
export interface Validation {
  passed?: boolean;
  checks?: string[];
  unverified_checks?: string[];
  issues?: { code: string; severity: string; message: string; day?: string }[];
}
export interface TraceEvent {
  stage: string;
  summary?: string;
  tool?: string;
  args?: Record<string, unknown>;
  count?: number;
  ok?: boolean;
  passed?: boolean;
  errors?: string[];
  duration_ms?: number;
  status?: string;
  attempt?: number;
  error_code?: string;
}
export interface Metrics {
  duration_ms?: number;
  model_calls?: number;
  tool_calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  repairs?: number;
  time_to_draft_ms?: number;
  draft_repairs?: number;
}
export interface PlanResponse {
  thread_id: string;
  status: string;
  reply: string;
  skill_used: string;
  plan: {
    city?: string;
    start_date?: string;
    end_date?: string;
    plan_content: string;
    version?: string;
    itinerary?: Itinerary;
  };
  requirements: Requirements;
  validation: Validation;
  evidence: Evidence[];
  trace: TraceEvent[];
  metrics: Metrics;
  degraded: boolean;
  error_msg?: string;
  persisted: boolean;
  pending_choice?: PendingChoice | null;
  route_draft?: RouteDraft | null;
}
export interface ChoiceOption {
  evidence_id: string;
  name: string;
  address: string;
  retrieval_hint: string;
  route_relation?: string;
  source: string;
  fetched_at: string;
}
export interface ChoiceSelection {
  token: string;
  automatic?: boolean;
  hotel_mode?: ChoiceMode;
  restaurant_mode?: ChoiceMode;
  hotel_evidence_id?: string | null;
  restaurant_evidence_ids?: string[];
}
export interface PendingChoice {
  token: string;
  city: string;
  message: string;
  trip_summary?: string;
  draft_id?: string;
  selection_policy?: "prefer_or_lock";
  preferred_options?: {
    hotel_evidence_id?: string;
    restaurant_evidence_ids?: string[];
  };
  no_progress?: boolean;
  automatic_retry_blocked?: boolean;
  hotels: ChoiceOption[];
  restaurants: ChoiceOption[];
  selected_options: {
    hotel_evidence_id?: string;
    restaurant_evidence_ids?: string[];
  };
}
export interface Conversation {
  thread_id: string;
  city?: string;
  status?: string;
  message_count: number;
  updated_at: string;
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}
export interface SavedPlan {
  version?: string;
  markdown: string;
  itinerary: Itinerary;
  evidence: Evidence[];
  requirements: Requirements;
  validation: Validation;
}

export type ChoiceMode = "prefer" | "lock" | "automatic";
export interface RouteDraft {
  requirements?: Requirements;
  draft_id: string;
  run_id: string;
  requirements_key: string;
  city: string;
  days: { date: string; theme: string; attraction_evidence_ids: string[] }[];
  rationale: string;
  warnings: string[];
  checked: string[];
  unchecked: string[];
  evidence: Evidence[];
}

export interface BrowseContext {
  date: string;
  anchorId: string;
  anchorName: string;
  category: "hotel" | "restaurant";
}
export interface BrowseResult {
  plan_version: string;
  date: string;
  category: string;
  anchor_evidence_id: string;
  anchor_name: string;
  city: string;
  relation: string;
  notice: string;
  items: {
    poi_id: string;
    name: string;
    address: string;
    source: string;
    fetched_at: string;
    distance_km: number | null;
    images: { url: string; source: string; poi_id: string }[];
  }[];
}
