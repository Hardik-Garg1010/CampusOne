export type Source = {
  chunk_id?: string;
  domain?: string;
  title?: string;
  source?: string;
  source_url?: string;
  section?: string;
  text?: string;
  verified_at?: string;
  academic_year?: string;
  score?: number;
};

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

export type AskResponse = {
  message: string;
  decision?: "ROUTE" | "CLARIFY" | "HANDOFF" | "NOT_FOUND" | string;
  domain?: string | null;
  routing?: {
    domain?: string | null;
    top_score?: number;
    second_domain?: string | null;
    second_score?: number;
    margin?: number;
    decision?: string;
    reason?: string;
    scores?: Record<string, number>;
  };
  sources?: Source[];
};

export async function askCampusOne(
  question: string,
  history: ChatTurn[] = [],
): Promise<AskResponse> {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, history: history.slice(-10) }),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(
      data?.detail || data?.message || "CampusOne could not process the request.",
    );
  }

  return data as AskResponse;
}
