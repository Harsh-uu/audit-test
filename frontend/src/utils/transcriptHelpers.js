/** Strip leading/trailing curly quotes and truncate for searching */
export function cleanExcerpt(excerpt) {
  return (excerpt || "")
    .replace(/^[\u201C\u201D\u2018\u2019"']+|[\u201C\u201D\u2018\u2019"']+$/g, "")
    .trim()
    .slice(0, 120);
}

/**
 * Find the best searchable substring of an excerpt within text.
 * First tries the full cleaned excerpt; if not found, falls back to
 * progressively shorter word-prefix matches (10 → 8 → 6 → 4 words).
 * This handles cases where the AI paraphrases a quote very slightly.
 * Returns the matched string, or "" if nothing was found.
 */
export function resolveExcerptQuery(text, excerpt) {
  // Strip [MM:SS] timestamp and optional "SpeakerName: " prefix the AI may have included
  const cleaned = cleanExcerpt(excerpt)
    .replace(/^\[\d{1,2}:\d{2}\]\s*/, "")
    .replace(/^[^:]{1,50}:\s*/, "");
  if (!cleaned) return "";
  const tLower = text.toLowerCase();

  if (tLower.includes(cleaned.toLowerCase())) return cleaned;

  const words = cleaned.split(/\s+/).filter(Boolean);
  for (const n of [10, 8, 6, 4]) {
    if (words.length <= n) continue;
    const partial = words.slice(0, n).join(" ");
    if (tLower.includes(partial.toLowerCase())) return partial;
  }

  if (words.length >= 4) {
    const partial = words.slice(0, 4).join(" ");
    if (tLower.includes(partial.toLowerCase())) return partial;
  }

  return "";
}

/** Escape special regex chars */
export function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function formatTranscript(text) {
  if (!text) return [];
  const lines = text.split(/\n+/).map(l => l.trim()).filter(Boolean);
  if (lines.length > 2) return lines;
  const sentences = text.match(/[^.!?]+[.!?]+["']?\s*/g) || [text];
  const paragraphs = [];
  for (let i = 0; i < sentences.length; i += 3) {
    const chunk = sentences.slice(i, i + 3).join("").trim();
    if (chunk) paragraphs.push(chunk);
  }
  return paragraphs.length ? paragraphs : [text];
}

export function parseSpeakerText(text) {
  if (!text) return [];
  const turns = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    // Extract optional [MM:SS] timestamp prefix
    const tsMatch = trimmed.match(/^\[(\d{1,2}:\d{2})\]\s+(.+)/);
    const timestamp = tsMatch ? tsMatch[1] : null;
    const rest = tsMatch ? tsMatch[2] : trimmed;
    const match = rest.match(/^([^:]{1,50}):\s*(.+)/);
    if (match) {
      turns.push({ speaker: match[1].trim(), text: match[2].trim(), timestamp });
    } else if (turns.length > 0) {
      turns[turns.length - 1].text += " " + rest;
    } else {
      turns.push({ speaker: "Speaker", text: rest, timestamp });
    }
  }
  return turns;
}

export function serializeTurns(turns) {
  return turns.map(t => t.timestamp ? `[${t.timestamp}] ${t.speaker}: ${t.text}` : `${t.speaker}: ${t.text}`).join("\n");
}

// ── Speaker colour palette — pastel / -300 range ─────────────────────────────
// Hues spread evenly around the colour wheel (~35° apart) so no two swatches
// read as "the same colour" — earlier version had two look-alike greens
// (emerald-300 + green-300) and an orange/amber pair that read the same.
export const SPEAKER_PALETTE = [
  "#FCA5A5",  // red-300
  "#FDBA74",  // orange-300
  "#FDE047",  // yellow-300
  "#BEF264",  // lime-300
  "#86EFAC",  // green-300
  "#5EEAD4",  // teal-300
  "#93C5FD",  // blue-300
  "#A5B4FC",  // indigo-300
  "#D8B4FE",  // purple-300
  "#F9A8D4",  // pink-300
];

/** Deterministic default colour for a speaker by their order of first appearance —
 *  ensures every speaker gets a distinct colour out of the box, not grey. */
export function getDefaultSpeakerColor(index) {
  return SPEAKER_PALETTE[index % SPEAKER_PALETTE.length];
}

/** Return dark or white text based on background luminance */
export function getContrastColor(hex) {
  if (!hex || hex.length < 7) return "#fff";
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? "#374151" : "#ffffff";
}
