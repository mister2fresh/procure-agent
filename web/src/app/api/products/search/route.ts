const apiBaseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function GET(req: Request): Promise<Response> {
  const qs = new URL(req.url).searchParams.toString();
  const upstream = await fetch(`${apiBaseUrl}/products/search?${qs}`, {
    cache: "no-store",
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
