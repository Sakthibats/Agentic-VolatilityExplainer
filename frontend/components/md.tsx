import { Fragment, type ReactNode } from "react";

import type { Citation } from "@/lib/api";

/* The model occasionally emits markdown bold in prose fields. Render **bold** as
   <strong> and leave everything else as plain text — a full markdown renderer is
   deliberately avoided (model output is untrusted; no links/html from it).

   A `[n]` marker becomes a link only when `citations` has that number. The URL always
   comes from the server's citation list, never from the text, and only http(s) renders. */
export function Md({ text, citations = [] }: { text: string; citations?: Citation[] }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i}>{withCitations(part, citations)}</strong>
        ) : (
          <Fragment key={i}>{withCitations(part, citations)}</Fragment>
        ),
      )}
    </>
  );
}

export function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function withCitations(text: string, citations: Citation[]): ReactNode {
  if (citations.length === 0) return text;
  return text.split(/(\[\d+\])/g).map((piece, i) => {
    const number = /^\[(\d+)\]$/.exec(piece)?.[1];
    const citation = number ? citations.find((c) => c.number === Number(number)) : undefined;
    if (!citation || !isWebUrl(citation.url)) return <Fragment key={i}>{piece}</Fragment>;
    return (
      <sup key={i}>
        <a
          href={citation.url}
          target="_blank"
          rel="noopener noreferrer"
          title={citation.source}
          className="px-0.5 text-primary underline-offset-2 hover:underline"
        >
          [{citation.number}]
        </a>
      </sup>
    );
  });
}
