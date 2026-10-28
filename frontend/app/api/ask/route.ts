import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const question = String(body?.question || "").trim();
    const history = Array.isArray(body?.history) ? body.history : [];

    if (!question) {
      return NextResponse.json(
        { detail: "Please enter a question." },
        { status: 400 },
      );
    }

    // Accept only the minimal, bounded conversation shape expected by the API.
    const safeHistory = history
      .filter(
        (item: unknown): item is { role: "user" | "assistant"; content: string } =>
          typeof item === "object" &&
          item !== null &&
          "role" in item &&
          "content" in item &&
          ((item as { role: unknown }).role === "user" ||
            (item as { role: unknown }).role === "assistant") &&
          typeof (item as { content: unknown }).content === "string",
      )
      .slice(-10)
      .map((item) => ({
        role: item.role,
        content: item.content.slice(0, 4000),
      }));

    const response = await fetch(`${BACKEND_URL}/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ question, history: safeHistory }),
      cache: "no-store",
    });

    const data = await response.json().catch(() => ({
      detail: "The CampusOne backend returned an invalid response.",
    }));

    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json(
      {
        detail:
          "CampusOne is unable to reach the backend. Make sure the backend is running on port 8000.",
      },
      { status: 502 },
    );
  }
}
