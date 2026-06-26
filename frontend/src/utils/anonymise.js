/**
 * Anonymise a person's name to their first initial: "Jane Smith" → "J."
 * Used for names appearing inside transcript text.
 */
export function anonymiseName(name) {
  if (!name || typeof name !== "string") return "—";
  const trimmed = name.trim();
  if (!trimmed) return "—";
  return trimmed[0].toUpperCase() + ".";
}

/**
 * Replace all known attendee names inside a block of transcript text
 * with their first-name initial. Matches full names and first names.
 */
export function anonymiseTranscript(text, attendees = []) {
  if (!text) return text;
  let result = text;
  const sorted = [...attendees]
    .filter(a => a?.name)
    .sort((a, b) => b.name.length - a.name.length); // longest first to avoid partial matches

  for (const a of sorted) {
    const parts = a.name.trim().split(/\s+/);
    const initial = parts[0][0].toUpperCase() + ".";
    // Full name first
    result = result.replace(new RegExp(a.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), initial);
    // First name
    if (parts[0].length > 2) {
      result = result.replace(new RegExp(`\\b${parts[0].replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi"), initial);
    }
  }
  return result;
}
