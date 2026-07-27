import { Fragment } from "react";

/* The model occasionally emits markdown bold in prose fields. Render **bold** as
   <strong> and leave everything else as plain text — a full markdown renderer is
   deliberately avoided (model output is untrusted; no links/html from it). */
export function Md({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}
