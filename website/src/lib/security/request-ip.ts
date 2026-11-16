import { headers } from "next/headers";

export async function getRequestIp(): Promise<string | null> {
  const headerStore = await headers();
  return (
    headerStore.get("cf-connecting-ip") ??
    headerStore.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    null
  );
}
