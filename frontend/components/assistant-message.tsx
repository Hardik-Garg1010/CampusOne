import {
  AlertCircle,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import type { AskResponse } from "@/lib/api";
import { SourceCard } from "./source-card";

type AssistantMessageProps = {
  response: AskResponse;
};

function cleanAnswer(message: string) {
  return message
    .replace(/\r\n/g, "\n")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .split(/\n\s*Sources:\s*/i)[0]
    .replace(/\s*\[Source\s*\d+\]\s*/gi, "")
    .trim();
}

function formatAnswer(message: string) {
  const cleaned = cleanAnswer(message);

  const lines = cleaned
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const result: Array<{
    type: "intro" | "bullet" | "text";
    text: string;
  }> = [];

  for (const line of lines) {
    if (line === "Here’s what I found:" || line === "Here's what I found:") {
      result.push({
        type: "intro",
        text: line,
      });
      continue;
    }

    if (line.startsWith("•")) {
      let text = line.replace(/^•\s*/, "").trim();

      // Retrieved KB content can contain Markdown heading markers.
      // Strip those markers because the fallback answer is rendered
      // as controlled UI text rather than arbitrary Markdown.
      text = text.replace(/^#{1,6}\s*/, "");

      result.push({
        type: "bullet",
        text,
      });
      continue;
    }

    result.push({
      type: "text",
      text: line.replace(/^#{1,6}\s*/, ""),
    });
  }

  return result;
}

export function AssistantMessage({
  response,
}: AssistantMessageProps) {
  const clarification = response.decision === "CLARIFY";
  const domain = response.routing?.domain || response.domain;

  return (
    <div className="glass-strong liquid-highlight rounded-[28px] p-5 text-left sm:p-6">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] bg-black text-white shadow-lg">
          {clarification ? (
            <AlertCircle className="h-4 w-4" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold">
              CampusOne
            </span>

            {domain && !clarification && (
              <span className="rounded-full border border-black/5 bg-black/[0.04] px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-black/35">
                {domain}
              </span>
            )}

            {clarification && (
              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-amber-700/70">
                Clarification
              </span>
            )}
          </div>

          <div className="mt-4 text-[14px] leading-7 text-black/65">
            <div className="space-y-3">
              {formatAnswer(response.message).map((item, index) => {
                if (item.type === "intro") {
                  return (
                    <p
                      key={index}
                      className="mb-4 text-[15px] font-medium text-black/55"
                    >
                      {item.text}
                    </p>
                  );
                }

                if (item.type === "bullet") {
                  return (
                    <div
                      key={index}
                      className="flex gap-3 leading-7 text-black/65"
                    >
                      <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-black/25" />
                      <p className="min-w-0">
                        {item.text}
                      </p>
                    </div>
                  );
                }

                return (
                  <p
                    key={index}
                    className="leading-7 text-black/65"
                  >
                    {item.text}
                  </p>
                );
              })}
            </div>
          </div>

          {clarification ? (
            <div className="mt-5 flex items-center gap-2 text-[10px] text-black/35">
              <AlertCircle className="h-3.5 w-3.5" />
              CampusOne is asking before routing your request.
            </div>
          ) : (
            <div className="mt-5 flex items-center gap-2 text-[10px] text-emerald-700/60">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Answer grounded in the CampusOne knowledge base
            </div>
          )}

          {response.sources && response.sources.length > 0 && (
            <div className="mt-5 border-t border-black/5 pt-4">
              <div className="mb-2.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-black/30">
                Sources
              </div>

              <div className="grid gap-2">
                {response.sources.slice(0, 3).map((source, index) => (
                  <SourceCard
                    key={`${source.chunk_id || "source"}-${index}`}
                    source={source}
                    index={index}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
