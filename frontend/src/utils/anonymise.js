/**
 * Anonymise a person's display name to just the initial of their first name.
 * "Jane Smith"  → "J."
 * "John"        → "J."
 */
export function anonymiseName(name) {
  if (!name || typeof name !== "string") return "—";
  const trimmed = name.trim();
  if (!trimmed) return "—";
  return trimmed[0].toUpperCase() + ".";
}
