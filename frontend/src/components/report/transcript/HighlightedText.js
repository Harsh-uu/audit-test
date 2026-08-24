import React from "react";
import { cleanExcerpt } from "@/utils/transcriptHelpers";

/** Render text with a highlighted substring */
export function HighlightedText({ text, query }) {
  if (!query) return <>{text}</>;
  const q = cleanExcerpt(query).toLowerCase();
  if (!q) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(q);
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-200 text-gray-900 rounded-sm px-0.5 not-italic">{text.slice(idx, idx + q.length)}</mark>
      {text.slice(idx + q.length)}
    </>
  );
}

/** Render text with multiple highlighted spans — supports current (amber) + other (yellow) */
export function MultiHighlightText({ text, matches, currentGlobalIdx }) {
  if (!matches || !matches.length) return <>{text}</>;
  const parts = [];
  let last = 0;
  for (const { start, end, globalIdx } of matches) {
    if (start > last) parts.push(<span key={`t${last}`}>{text.slice(last, start)}</span>);
    const isCurrent = globalIdx === currentGlobalIdx;
    parts.push(
      <mark
        key={`m${globalIdx}`}
        data-find-match={isCurrent ? "current" : undefined}
        className={`rounded-sm px-0.5 not-italic transition-colors ${
          isCurrent ? "bg-orange-300 text-gray-900 ring-1 ring-orange-400" : "bg-yellow-200 text-gray-900"
        }`}
      >
        {text.slice(start, end)}
      </mark>
    );
    last = end;
  }
  if (last < text.length) parts.push(<span key="tail">{text.slice(last)}</span>);
  return <>{parts}</>;
}
