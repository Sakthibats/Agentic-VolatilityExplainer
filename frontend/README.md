# Frontend — Agentic Market Explainer

Next.js (App Router) + Tailwind v4 + shadcn/ui. Talks to the FastAPI backend over the
versioned `/v1` REST + SSE API only — never imports backend code.

```bash
npm install
npm run dev     # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` to point at the backend (defaults to `http://localhost:8080`).

- `lib/api.ts` mirrors `backend/volatility_explainer/api/schemas.py` — that file is the
  contract; keep these types in sync with it.
- `app/globals.css` holds the design tokens. Light = white + blue; dark = trading terminal.
  Both themes come from the same variables.
- `components/analytics.tsx` loads the GA4 tag (`gtag.js`) via `next/script` from the root
  layout. It renders only in production builds, so `npm run dev` sends nothing. The
  measurement ID is a public value and lives in that file; set `NEXT_PUBLIC_GA_ID` to
  override it. Client-side route changes are counted by GA4 Enhanced Measurement
  ("page changes based on browser history events") — keep that setting on in the GA admin
  panel, since the SPA fires no extra `page_view` calls.
