import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, Loader2, MapPin, BedDouble, Navigation, Utensils, CloudSun, Thermometer } from 'lucide-react';
import type { PlanRequest, PlanResponse, TripPlan, DayPlan } from './types';

// --- Types ---
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  plan?: TripPlan;
  skill_used?: string;
  loading?: boolean;
}

// --- Main App ---
export default function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'greeting',
      role: 'assistant',
      content: 'Tell me your destination, dates, and what kind of journey you seek.',
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Dummy NLP extractor to satisfy backend required fields from natural language
  const extractParams = (text: string): PlanRequest => {
    const defaultCityMatch = text.match(/(北京|上海|京都|巴黎|东京|伦敦|成都|广州|深圳|杭州|西安|大理|丽江|三亚)/);
    const city = defaultCityMatch ? defaultCityMatch[1] : '京都'; // Fallback
    
    // Fallback dates (in a real app, you'd use LLM to extract this before hitting the trip API, or let the backend do it)
    const start_date = '2026-10-15';
    const end_date = '2026-10-18';

    return {
      city,
      start_date,
      end_date,
      preferences: text, // Send the whole prompt as preferences to let the LLM figure it out
      accommodation: '不限'
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
    };
    
    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsTyping(true);

    const loadingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, {
      id: loadingId,
      role: 'assistant',
      content: 'Crafting your journey...',
      loading: true
    }]);

    try {
      const payload = extractParams(userMessage.content);
      const res = await fetch('/api/v1/trips', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error('API Error');
      const data: PlanResponse = await res.json();
      
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: loadingId,
        role: 'assistant',
        content: data.plan.overall_suggestions || `I have curated a journey to ${data.plan.city} for you.`,
        plan: data.plan,
        skill_used: data.skill_used
      } : m));

    } catch (error) {
      // Mock Data Fallback
      setTimeout(() => {
        setMessages(prev => prev.map(m => m.id === loadingId ? {
          id: loadingId,
          role: 'assistant',
          content: mockResponse.plan.overall_suggestions,
          plan: mockResponse.plan,
          skill_used: mockResponse.skill_used
        } : m));
      }, 2000);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-background text-foreground font-sans selection:bg-foreground selection:text-background">
      {/* Header */}
      <header className="flex-none p-6 md:p-8 flex items-center justify-between z-10 sticky top-0 bg-background/80 backdrop-blur-md">
        <h1 className="font-serif text-xl italic tracking-wide">Voyage.</h1>
        <div className="text-[10px] font-mono uppercase tracking-widest text-muted">
          AI Travel Architect
        </div>
      </header>

      {/* Chat Stream */}
      <main className="flex-1 overflow-y-auto px-6 md:px-8 pb-32 w-full max-w-4xl mx-auto flex flex-col gap-16 pt-10">
        <AnimatePresence initial={false}>
          {messages.map((msg) => (
            <MessageItem key={msg.id} msg={msg} />
          ))}
        </AnimatePresence>
        <div ref={bottomRef} className="h-4" />
      </main>

      {/* Input Area */}
      <footer className="flex-none p-6 md:p-8 fixed bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background to-transparent pointer-events-none">
        <div className="max-w-3xl mx-auto pointer-events-auto">
          <form 
            onSubmit={handleSubmit}
            className="relative flex items-center border border-border bg-surface shadow-sm focus-within:border-foreground transition-colors duration-500 rounded-none"
          >
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="e.g. 3 days in Kyoto, deep culture, quiet places..."
              className="w-full bg-transparent p-4 md:p-5 outline-none font-serif text-lg placeholder:text-muted/40 placeholder:font-sans placeholder:text-sm"
              disabled={isTyping}
            />
            <button 
              type="submit"
              disabled={!inputValue.trim() || isTyping}
              className="absolute right-2 p-3 text-muted hover:text-foreground disabled:opacity-30 transition-colors"
            >
              {isTyping ? <Loader2 className="w-5 h-5 animate-spin" /> : <ArrowUp className="w-5 h-5" />}
            </button>
          </form>
          <div className="text-center mt-4">
            <span className="text-[10px] font-mono text-muted uppercase tracking-widest">
              Natural Language Engine
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

// --- Components ---

function MessageItem({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex flex-col w-full ${isUser ? 'items-end' : 'items-start'}`}
    >
      {/* Role Label */}
      <div className="text-[10px] font-mono uppercase tracking-widest text-muted mb-3 flex items-center gap-2">
        {!isUser && <span className="w-1.5 h-1.5 bg-accent block rounded-full" />}
        {isUser ? 'You' : 'Architect'}
      </div>

      {/* Message Content */}
      <div className={`max-w-2xl ${isUser ? 'text-right' : 'text-left'}`}>
        {msg.loading ? (
          <div className="flex items-center gap-3 text-muted">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="font-serif italic text-lg">{msg.content}</span>
          </div>
        ) : (
          <p className={`text-xl md:text-2xl leading-relaxed ${isUser ? 'font-serif text-foreground/90' : 'font-sans font-light text-foreground'}`}>
            {msg.content}
          </p>
        )}
      </div>

      {/* Render Structured Plan if available */}
      {msg.plan && !msg.loading && (
        <motion.div 
          initial={{ opacity: 0, marginTop: 0 }}
          animate={{ opacity: 1, marginTop: 40 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="w-full border border-border bg-surface p-8 md:p-12"
        >
          {/* Plan Header */}
          <div className="flex flex-wrap gap-4 items-center justify-between border-b border-border pb-6 mb-10">
            <div>
              <h3 className="font-serif text-4xl mb-2 flex items-center gap-3">
                <MapPin className="w-6 h-6 text-muted" /> {msg.plan.city}
              </h3>
              <div className="text-xs font-mono uppercase tracking-widest text-muted">
                {msg.plan.start_date} — {msg.plan.end_date}
              </div>
            </div>
            {msg.skill_used && (
              <div className="border border-border px-3 py-1 text-[10px] font-mono uppercase tracking-widest text-muted">
                Engine: {msg.skill_used}
              </div>
            )}
          </div>

          {/* Weather & Budget Brief */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-12">
            <div className="col-span-2">
              <div className="text-[10px] font-mono uppercase tracking-widest text-muted mb-3">Climate Expectation</div>
              <div className="flex items-center gap-4">
                {msg.plan.weather_info.slice(0, 2).map((w, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <CloudSun className="w-4 h-4 text-muted" />
                    <span>{w.day_temp}°C {w.day_weather}</span>
                  </div>
                ))}
              </div>
            </div>
            {msg.plan.budget && (
              <div className="col-span-2 md:text-right">
                <div className="text-[10px] font-mono uppercase tracking-widest text-muted mb-3">Est. Budget</div>
                <div className="font-serif text-xl">¥{msg.plan.budget.total}</div>
              </div>
            )}
          </div>

          {/* Timeline */}
          <div className="space-y-16">
            {msg.plan.days.map((day, idx) => (
              <div key={idx} className="relative pl-6 border-l border-border hover:border-foreground/30 transition-colors">
                <div className="absolute top-1.5 left-[-4px] w-2 h-2 bg-background border border-border rounded-full" />
                
                <div className="mb-6">
                  <div className="text-[10px] font-mono uppercase tracking-widest text-muted mb-2">Day {day.day_index + 1} // {day.date}</div>
                  <h4 className="font-serif text-2xl">{day.description}</h4>
                </div>

                <div className="space-y-6">
                  {day.hotel && (
                    <div className="flex items-start gap-4 group">
                      <BedDouble className="w-4 h-4 text-muted mt-1" />
                      <div>
                        <div className="font-medium text-sm mb-1">{day.hotel.name} <span className="text-muted font-normal text-xs ml-2">{day.hotel.type}</span></div>
                        <div className="text-xs text-muted font-sans">{day.hotel.address}</div>
                      </div>
                    </div>
                  )}

                  {day.attractions.map((attr, i) => (
                    <div key={i} className="flex items-start gap-4">
                      <Navigation className="w-4 h-4 text-muted mt-1" />
                      <div>
                        <div className="font-medium text-sm mb-1">{attr.name} <span className="font-mono text-muted text-xs ml-2">{attr.visit_duration}m</span></div>
                        <div className="text-xs text-muted/80 leading-relaxed max-w-lg">{attr.description}</div>
                      </div>
                    </div>
                  ))}

                  {day.meals.map((meal, i) => (
                    <div key={i} className="flex items-start gap-4">
                      <Utensils className="w-4 h-4 text-muted mt-1" />
                      <div>
                        <div className="font-medium text-sm mb-1">{meal.name} <span className="text-[10px] font-mono uppercase tracking-widest text-muted ml-2">{meal.type}</span></div>
                        <div className="text-xs text-muted/80">{meal.description}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

// --- Mock Data Fallback ---
const mockResponse: PlanResponse = {
  skill_used: "深度人文游",
  plan: {
    city: "京都",
    start_date: "2026-10-15",
    end_date: "2026-10-18",
    overall_suggestions: "Based on your request, I've designed a curated journey focusing on the philosophy of Wabi-sabi. We'll avoid crowded spots, focusing instead on hidden Zen gardens and artisan workshops.",
    weather_info: [
      { date: "2026-10-15", day_weather: "晴朗", night_weather: "多云", day_temp: 22, night_temp: 14, wind_direction: "北风", wind_power: "微风" },
      { date: "2026-10-16", day_weather: "多云", night_weather: "小雨", day_temp: 20, night_temp: 13, wind_direction: "东风", wind_power: "微风" }
    ],
    budget: {
      total_ticket_fee: 450,
      total_hotels: 3600,
      total_meals: 2800,
      total_transportation: 300,
      total: 7150
    },
    days: [
      {
        date: "2026-10-15",
        day_index: 0,
        description: "Arrival & The Art of Silence",
        transportation: "专车接机",
        accommodation: "奢华町屋",
        hotel: {
          name: "Aman Kyoto",
          address: "1 Okitayama Washimine-cho, Kita-ku",
          price_range: "奢华",
          rating: "4.9/5",
          distance: "隐逸山林",
          type: "Resort",
          estimated_cost: 1800
        },
        attractions: [
          {
            name: "Genko-an Temple (源光庵)",
            address: "47 Takagamine Donouchicho",
            visit_duration: 90,
            description: "Famous for the 'Window of Enlightenment' and 'Window of Confusion'. A perfect place for meditation away from tourists.",
            ticket_price: 50,
            location: { longitude: 135.733, latitude: 35.056 }
          }
        ],
        meals: [
          {
            type: "dinner",
            name: "Mizai (未在)",
            address: "Maruyama Park",
            description: "Three-star Michelin Kaiseki. A masterclass in seasonal minimalism.",
            estimated_cost: 1500
          }
        ]
      }
    ]
  }
};
