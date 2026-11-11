"use client";

import CareGapsTool from "@/components/careGapsTool/CareGapsTool";
import ClaimHistoryTool from "@/components/claimHistoryTool/ClaimHistoryTool";
import ClinicalHistoryTool from "@/components/clinicalHistoryTool/ClinicalHistoryTool";
import CostEstimator from "@/components/costEstimator/CostEstimator";
import DecisionTracingTool from "@/components/decisionTracingTool/DecisionTracingTool";
import PlanComparisonTool from "@/components/planComparisonTool/PlanComparisonTool";
import Skeleton from "@/components/skeleton/Skeleton";
import { useToolData } from "./useToolData";
import styles from "./ToolContent.module.css";

/**
 * Routes a tool id to its content. Each tool reads from routes that already
 * exist in the backend — see useToolData for the mapping.
 */
export default function ToolContent({ toolId, member }) {
  const { data, loading, error } = useToolData(toolId, member);

  if (toolId === "clinical-history-review") {
    return <ClinicalHistoryTool member={member} />;
  }

  // Fetches nothing — it owns its own brief skeleton before the empty state.
  if (toolId === "recent-care-gaps") return <CareGapsTool />;

  if (loading) return <Skeleton lines={7} />;

  if (error) {
    return <p className={styles.error}>Could not load this tool ({error.message}).</p>;
  }

  if (!data) return <Skeleton lines={7} />;

  if (toolId === "claim-history")
    return <ClaimHistoryTool claims={data.claims} />;
  if (toolId === "decision-tracing")
    return <DecisionTracingTool traces={data.traces} />;
  if (toolId === "premium-calculation")
    return <CostEstimator data={data} member={member} />;
  if (toolId === "plan-comparison")
    return <PlanComparisonTool data={data} member={member} />;

  return <p className={styles.empty}>This tool has no content yet.</p>;
}
