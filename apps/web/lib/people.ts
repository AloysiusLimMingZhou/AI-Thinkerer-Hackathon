import type { Person, PersonId } from "./types";

/** Everyone who appears in the fixtures. The owner is "you" throughout the UI. */
export const OWNER = { name: "Aloysius Lim", short: "Aloy", initials: "AL" } as const;
export const AGENT_NAME = "Aloy-bot";

const people: Person[] = [
  { id: "aloy", name: "Aloysius Lim", role: "Engineering lead, Platform" },
  { id: "priya", name: "Priya Raman", role: "Engineering manager, Payments" },
  { id: "marcus", name: "Marcus Chen", role: "Backend engineer, Payments" },
  { id: "farah", name: "Farah Aziz", role: "Product manager, Payments" },
  { id: "daniel", name: "Daniel Ong", role: "Finance operations" },
  { id: "weijie", name: "Wei Jie Tan", short: "Wei Jie", role: "Site reliability engineer" },
  { id: "hana", name: "Hana Kobayashi", role: "Design lead" },
  { id: "sofia", name: "Sofia Alvarez", role: "Product designer" },
  { id: "arjun", name: "Arjun Menon", role: "Frontend engineer" },
  { id: "meiling", name: "Mei Ling Goh", short: "Mei Ling", role: "Product manager, Growth" },
  { id: "kenji", name: "Kenji Sato", role: "Data analyst" },
  { id: "isabel", name: "Isabel Cruz", role: "Marketing lead" },
  { id: "nadia", name: "Nadia Rahman", role: "Platform engineer" },
  { id: "tom", name: "Tom Becker", role: "Platform engineer" },
  { id: "ravi", name: "Ravi Kumar", role: "Platform engineer" },
  { id: "sam", name: "Sam Whitfield", role: "Security engineer" },
  { id: "rachel", name: "Rachel Tan", role: "Chief executive" },
  { id: "ben", name: "Ben Okafor", role: "VP of Engineering" },
  { id: "joanna", name: "Joanna Lee", role: "Head of People" },
  { id: "lars", name: "Lars Eriksen", role: "Account manager", org: "Adyen" },
  { id: "chloe", name: "Chloe Martin", role: "Solutions engineer", org: "Adyen" },
];

const byId = new Map(people.map((p) => [p.id, p]));

export function person(id: PersonId): Person {
  const p = byId.get(id);
  if (!p) throw new Error(`Unknown person: ${id}`);
  return p;
}

export function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** The name colleagues use: "Mei Ling" for Mei Ling Goh, "Priya" for Priya Raman. */
export function shortName(p: Person): string {
  return p.short ?? p.name.split(/\s+/)[0] ?? p.name;
}
