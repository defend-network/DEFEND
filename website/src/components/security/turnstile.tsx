import Script from "next/script";

export function TurnstileScript() {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  if (!siteKey) return null;
  return (
    <Script
      src="https://challenges.cloudflare.com/turnstile/v0/api.js"
      strategy="afterInteractive"
    />
  );
}

export function TurnstileWidget() {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  if (!siteKey) return null;
  return (
    <div
      className="cf-turnstile"
      data-sitekey={siteKey}
      data-theme="light"
      data-language="en"
    />
  );
}
