"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";

type AssistantInputProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  loading?: boolean;
  compact?: boolean;
};

export function AssistantInput({
  value,
  onChange,
  onSubmit,
  loading = false,
  compact = false,
}: AssistantInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!loading && compact) inputRef.current?.focus();
  }, [loading, compact]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const question = value.trim();
    if (!question || loading) return;
    onSubmit(question);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={submit} className="w-full">
      <div
        className={[
          "glass-strong liquid-highlight rounded-[28px] p-2.5 transition-all duration-300",
          focused
            ? "shadow-[0_25px_90px_rgba(0,0,0,0.12)]"
            : "shadow-[0_20px_70px_rgba(0,0,0,0.08)]",
        ].join(" ")}
      >
        <div
          className={[
            "relative flex items-center gap-3 rounded-[21px] border border-white/70 bg-white/45 px-4 transition",
            compact ? "min-h-[64px]" : "min-h-[70px]",
          ].join(" ")}
        >
          <Sparkles className="h-[18px] w-[18px] shrink-0 text-black/40" />

          <input
            ref={inputRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            placeholder="Ask anything about Bennett University..."
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-black/30 sm:text-[15px]"
            aria-label="Ask CampusOne"
          />

          <button
            type="submit"
            disabled={!value.trim() || loading}
            aria-label="Ask CampusOne"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-black text-white shadow-[0_8px_25px_rgba(0,0,0,0.18)] transition duration-200 hover:scale-105 hover:bg-black/90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:scale-100"
          >
            {loading ? (
              <Loader2 className="h-[18px] w-[18px] animate-spin" />
            ) : (
              <ArrowUp className="h-[18px] w-[18px]" />
            )}
          </button>
        </div>

        <div className="flex items-center justify-between px-3 pb-0.5 pt-2 text-[10px] text-black/30 sm:px-4 sm:text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Grounded in official sources
          </span>
          <span className="hidden sm:block">Enter to ask</span>
        </div>
      </div>
    </form>
  );
}
