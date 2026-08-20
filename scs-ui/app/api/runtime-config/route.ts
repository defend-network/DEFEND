export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json({
    scsApiOrigin:
      process.env.SCS_API_ORIGIN ??
      process.env.NEXT_PUBLIC_SCS_API_ORIGIN ??
      "http://127.0.0.1:8100",
  });
}