import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const question = String(body?.question || "").trim();

    if (!question) {
      return NextResponse.json(
        { detail: "Please enter a question." },
        { status: 400 },
      );
    }

    const response = await fetch(`${BACKEND_URL}/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ question }),
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
