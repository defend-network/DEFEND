import { toNextJsHandler } from "better-auth/next-js";

import { getAuth } from "@/lib/auth/auth";

const handler = toNextJsHandler(async (request) => {
  const auth = await getAuth();
  return auth.handler(request);
});

export const dynamic = "force-dynamic";

export const { GET, POST, PATCH, PUT, DELETE } = handler;
