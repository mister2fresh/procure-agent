"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, resumeRun, startRun } from "@/lib/api";
import { type LineDecision, resumeRequestSchema } from "@/lib/schemas";

export async function startRunAction(formData: FormData): Promise<void> {
  const fixture = formData.get("fixture_filename");
  if (typeof fixture !== "string" || !fixture) {
    throw new Error("fixture_filename is required");
  }
  const snapshot = await startRun(fixture);
  redirect(`/runs/${snapshot.thread_id}`);
}

export type ResumeActionResult = { ok: true } | { ok: false; error: string };

export async function resumeRunAction(
  threadId: string,
  reviewer: string,
  overallNotes: string | null,
  lineDecisions: LineDecision[],
): Promise<ResumeActionResult> {
  const parsed = resumeRequestSchema.safeParse({
    reviewer,
    line_decisions: lineDecisions,
    overall_notes: overallNotes,
  });
  if (!parsed.success) {
    return { ok: false, error: parsed.error.issues[0]?.message ?? "invalid payload" };
  }
  try {
    await resumeRun(threadId, parsed.data);
  } catch (e) {
    if (e instanceof ApiError) {
      return { ok: false, error: e.message };
    }
    throw e;
  }
  revalidatePath(`/runs/${threadId}`);
  return { ok: true };
}
