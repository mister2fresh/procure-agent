const apiBaseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ filename: string }> },
): Promise<Response> {
  const { filename } = await params;
  const upstream = await fetch(`${apiBaseUrl}/fixtures/${encodeURIComponent(filename)}`, {
    cache: "no-store",
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "text/plain; charset=utf-8",
    },
  });
}
