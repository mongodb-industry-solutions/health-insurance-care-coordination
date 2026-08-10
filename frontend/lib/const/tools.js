/**
 * "Other Tools" rows. Pill tint and tag text are derived from `category`, so a
 * new tool only needs an entry here.
 */

export const TOOL_CATEGORIES = [
  { id: "insurance", label: "Insurance Policy & Information", tag: "insurance" },
  { id: "health", label: "Health Administration", tag: "health" },
];

export const TOOLS = [
  { id: "premium-calculation", label: "Premium Calculation", category: "insurance" },
  { id: "plan-comparison", label: "Plan Comparison", category: "insurance" },
  { id: "claim-history", label: "Claim History", category: "insurance" },
  { id: "clinical-history-review", label: "Clinical History Review", category: "health" },
  { id: "recent-care-gaps", label: "Recent Care Gaps", category: "health" },
];

export function getToolsByCategory(categoryId) {
  return TOOLS.filter((tool) => tool.category === categoryId);
}
