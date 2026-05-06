import "server-only";

import { z } from "zod";
import { type ResumeRequest, type RunSnapshot, runSnapshotSchema } from "@/lib/schemas";

const apiBaseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const fixturesSchema = z.array(z.string());

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function callApi<T>(path: string, init: RequestInit, parse: (raw: unknown) => T): Promise<T> {
  const res = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, `${path} → ${res.status}: ${detail}`);
  }
  return parse(await res.json());
}

export async function fetchFixtures(): Promise<string[]> {
  return callApi("/fixtures", { method: "GET" }, (raw) => fixturesSchema.parse(raw));
}

export async function startRun(fixtureFilename: string): Promise<RunSnapshot> {
  return callApi(
    "/runs",
    {
      method: "POST",
      body: JSON.stringify({ fixture_filename: fixtureFilename }),
    },
    (raw) => runSnapshotSchema.parse(raw),
  );
}

export async function fetchSnapshot(threadId: string): Promise<RunSnapshot> {
  return callApi(`/runs/${encodeURIComponent(threadId)}`, { method: "GET" }, (raw) =>
    runSnapshotSchema.parse(raw),
  );
}

export async function resumeRun(threadId: string, payload: ResumeRequest): Promise<RunSnapshot> {
  return callApi(
    `/runs/${encodeURIComponent(threadId)}/resume`,
    { method: "POST", body: JSON.stringify(payload) },
    (raw) => runSnapshotSchema.parse(raw),
  );
}
