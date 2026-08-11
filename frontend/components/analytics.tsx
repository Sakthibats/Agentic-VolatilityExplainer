import Script from "next/script";

/** GA4 measurement ID. Public by design (it ships in the page source), so it
 *  lives here rather than in an env file — the frontend commits no `.env`, and
 *  a static export would otherwise need the value wired into every build host.
 *  `NEXT_PUBLIC_GA_ID` still overrides it if a second property is ever needed. */
const GA_ID = process.env.NEXT_PUBLIC_GA_ID ?? "G-6LV0HY245P";

/** Google tag (gtag.js). Rendered only in production builds so local `npm run
 *  dev` traffic doesn't land in the property's reports.
 *
 *  `afterInteractive` (the next/script default) loads gtag right after
 *  hydration instead of blocking first paint. Pageviews for client-side
 *  navigations between routes are picked up by GA4 Enhanced Measurement's
 *  "page changes based on browser history events" — no manual page_view calls. */
export function Analytics() {
  if (process.env.NODE_ENV !== "production" || !GA_ID) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
        strategy="afterInteractive"
      />
      <Script id="gtag-init" strategy="afterInteractive">
        {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', '${GA_ID}');`}
      </Script>
    </>
  );
}
