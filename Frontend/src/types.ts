// API Types based on the Python backend implementation

export interface Location {
  longitude: number;
  latitude: number;
}

export interface Attraction {
  name: string;
  location: Location;
  address: string;
  visit_duration: number;
  description: string;
  category?: string;
  rating?: number;
  image_url?: string;
  ticket_price: number;
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack';
  name: string;
  address?: string;
  location?: Location;
  description?: string;
  estimated_cost: number;
}

export interface Hotel {
  name: string;
  address: string;
  location?: Location;
  price_range: string;
  rating: string;
  distance: string;
  type: string;
  estimated_cost: number;
}

export interface WeatherInfo {
  date: string;
  day_weather: string;
  night_weather: string;
  day_temp: number;
  night_temp: number;
  wind_direction: string;
  wind_power: string;
}

export interface Budget {
  total_ticket_fee: number;
  total_hotels: number;
  total_meals: number;
  total_transportation: number;
  total: number;
}

export interface DayPlan {
  date: string;
  day_index: number;
  description: string;
  transportation: string;
  accommodation: string;
  hotel?: Hotel;
  attractions: Attraction[];
  meals: Meal[];
}

export interface TripPlan {
  city: string;
  start_date: string;
  end_date: string;
  days: DayPlan[];
  weather_info: WeatherInfo[];
  overall_suggestions: string;
  budget?: Budget;
}

export interface PlanRequest {
  city: string;
  start_date: string;
  end_date: string;
  preferences?: string;
  accommodation?: string;
}

export interface PlanResponse {
  plan: {
    city: string;
    start_date: string;
    end_date: string;
    preferences: string;
    plan_content: string;
    steps: string[];
  };
  skill_used: string;
}

export interface SkillInfo {
  name: string;
  description: string;
  keywords: string[];
}
