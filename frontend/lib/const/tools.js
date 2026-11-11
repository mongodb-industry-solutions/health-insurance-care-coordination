/**
 * "Other Tools" rows. Pill tint, icon accent and tag text are derived from
 * `category`, so a new tool only needs an entry here.
 *
 * `icon` values are LeafyGreen glyph names. A few of the icons the design calls
 * for have no exact glyph in @leafygreen-ui/icon (there is no calculator, and no
 * clipboard-with-heartbeat), so the nearest available line icon is used.
 */

export const TOOL_CATEGORIES = [
  {
    id: "insurance",
    label: "Insurance Policy & Information",
    tag: "insurance",
  },
  { id: "health", label: "Health Administration", tag: "health" },
];

export const TOOLS = [
  {
    id: "premium-calculation",
    label: "Cost Estimator",
    category: "insurance",
    icon: "Coin", // no calculator glyph
  },
  {
    id: "plan-comparison",
    label: "Plan Comparison",
    category: "insurance",
    icon: "SplitVertical", // side-by-side columns
  },
  {
    id: "claim-history",
    label: "Claim History",
    category: "insurance",
    icon: "ClockWithArrow",
  },
  {
    id: "decision-tracing",
    label: "Decision Tracing",
    category: "insurance",
    icon: "Diagram3", // branching flow; stands in for a reasoning chain
  },
  {
    id: "clinical-history-review",
    label: "Clinical History Review",
    category: "health",
    icon: "ActivityFeed", // heartbeat line; no clipboard-with-heartbeat glyph
  },
  {
    id: "recent-care-gaps",
    label: "Recent Care Gaps",
    category: "health",
    icon: "ImportantWithCircle",
  },
];

export function getToolsByCategory(categoryId) {
  return TOOLS.filter((tool) => tool.category === categoryId);
}

export function getToolById(toolId) {
  return TOOLS.find((tool) => tool.id === toolId) ?? null;
}
