import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { PlanResponse } from './types';

// --- Types ---
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  plan_content?: string;
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
      const res = await fetch('/api/v1/chat_plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: userMessage.content }),
      });

      if (!res.ok) throw new Error('API Error');
      const data: PlanResponse = await res.json();
      
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: loadingId,
        role: 'assistant',
        content: `I have curated a journey to ${data.plan.city} for you.`,
        plan_content: data.plan.plan_content,
        skill_used: data.skill_used
      } : m));

    } catch (error) {
      // Mock Data Fallback
      setTimeout(() => {
        setMessages(prev => prev.map(m => m.id === loadingId ? {
          id: loadingId,
          role: 'assistant',
          content: "Here is a curated Mock journey.",
          plan_content: "### Kyoto 3 Days\n\nThis is a mock fallback markdown content.",
          skill_used: "Mock Engine"
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

      {/* Render Markdown Plan if available */}
      {msg.plan_content && !msg.loading && (
        <motion.div 
          initial={{ opacity: 0, marginTop: 0 }}
          animate={{ opacity: 1, marginTop: 40 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="w-full border border-border bg-surface p-8 md:p-12 prose prose-stone max-w-none prose-headings:font-serif prose-a:text-foreground prose-p:font-sans prose-p:leading-relaxed prose-li:font-sans"
        >
          {msg.skill_used && (
            <div className="inline-block border border-border px-3 py-1 text-[10px] font-mono uppercase tracking-widest text-muted mb-8">
              Engine: {msg.skill_used}
            </div>
          )}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {msg.plan_content}
          </ReactMarkdown>
        </motion.div>
      )}
    </motion.div>
  );
}
