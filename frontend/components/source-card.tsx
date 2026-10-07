import {
  ExternalLink,
  FileText,
} from "lucide-react";
import type { Source } from "@/lib/api";

type SourceCardProps = {
  source: Source;
  index: number;
};

function getDomain(url?: string) {
  if (!url) return "Bennett University knowledge base";

  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Bennett University";
  }
}

export function SourceCard({
  source,
  index,
}: SourceCardProps) {
  const label =
    source.title ||
    source.section ||
    source.domain ||
    "Bennett University source";

  const href = source.source_url;
  const domain = getDomain(href);

  const content = (
    <div className="group flex items-center gap-3 rounded-[16px] border border-white/70 bg-white/40 px-3.5 py-3 transition hover:bg-white/65">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-white/70 shadow-sm">
        <FileText className="h-3.5 w-3.5 text-black/45" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate text-[12px] font-medium text-black/70">
          {label}
        </div>

        <div className="mt-0.5 truncate text-[10px] text-black/35">
          {domain}
        </div>
      </div>

      {href ? (
        <ExternalLink className="h-3.5 w-3.5 shrink-0 text-black/25 transition group-hover:text-black/55" />
      ) : (
        <span className="text-[10px] text-black/25">
          #{index + 1}
        </span>
      )}
    </div>
  );

  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      {content}
    </a>
  ) : (
    content
  );
}