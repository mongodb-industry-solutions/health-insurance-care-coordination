"use client";

import { useState } from "react";
import AppHeader from "@/components/appHeader/AppHeader";
import Chatbot from "@/components/chatbot/Chatbot";
import DetailPanel from "@/components/detailPanel/DetailPanel";
import OtherTools from "@/components/otherTools/OtherTools";
import PatientIdentityCard from "@/components/patientIdentityCard/PatientIdentityCard";
import PendingActionsZone from "@/components/pendingActionsZone/PendingActionsZone";
import ProcessDock from "@/components/processOverlay/ProcessDock";
import ProcessOverlay from "@/components/processOverlay/ProcessOverlay";
import ToolDrawer from "@/components/toolDrawer/ToolDrawer";
import { toPatientLine, toPendingActions } from "@/lib/memberPresenter";
import { useMemberDashboard } from "./useMemberDashboard";
import styles from "./MemberDashboard.module.css";

/**
 * Main tab: patient context on the left, actions and tools on the right. The
 * process opens over the top of it, and minimises to a docked tab.
 *
 * The run state sits in `useMemberDashboard`, which stays mounted through all
 * three process states — that is what lets the docked tab keep reporting live
 * progress after the overlay is dismissed.
 *
 * @param {object} props.profile  The selected MEMBERS entry (avatar, names).
 * @param {() => void} props.onLogOut
 */
export default function MemberDashboard({ profile, onLogOut }) {
  const { member, loading, error, runningActionId, startProcess, run } =
    useMemberDashboard(profile.memberId);

  const [openTool, setOpenTool] = useState(null);
  // "hidden" | "open" | "docked" — the process is never modal to the run itself.
  const [processState, setProcessState] = useState("hidden");
  // Held rather than looked up: the action is resolved by the time the run ends.
  const [processAction, setProcessAction] = useState(null);

  const handleStartProcess = (actionId) => {
    const action = toPendingActions(member).find(
      (entry) => entry.id === actionId
    );

    setProcessAction(action ?? { id: actionId, label: "Prior Authorization" });
    setProcessState("open");
    startProcess(actionId);
  };

  const processTitle = processAction?.label ?? "Prior Authorization";

  return (
    <>
      <AppHeader onLogOut={onLogOut} />

      {error && (
        <p className={styles.notice}>
          Could not reach the backend ({error.message}). Showing what is
          available locally — check that the API is running.
        </p>
      )}

      {loading ? (
        <p className={styles.status}>Loading {profile.firstName}&apos;s record…</p>
      ) : (
        <div className={styles.layout}>
          <div>
            <PatientIdentityCard member={member} profile={profile} />
            <DetailPanel member={member} />
          </div>

          <div>
            <PendingActionsZone
              actions={toPendingActions(member)}
              runningActionId={runningActionId}
              onStartProcess={handleStartProcess}
            />
            <OtherTools onOpenTool={setOpenTool} />
          </div>
        </div>
      )}

      <ToolDrawer
        tool={openTool}
        member={member}
        onClose={() => setOpenTool(null)}
      />

      {processState === "open" && (
        <ProcessOverlay
          run={run}
          title={processTitle}
          patientLine={toPatientLine(member, profile)}
          onDock={() => setProcessState("docked")}
          onDismiss={() => setProcessState("hidden")}
        />
      )}

      {processState === "docked" && (
        <ProcessDock
          run={run}
          title={processTitle}
          onOpen={() => setProcessState("open")}
          onDismiss={() => setProcessState("hidden")}
        />
      )}

      {/* Mounted here rather than in the layout so the agents get the member as
          opening context — the questions it exists to answer are all about them. */}
      <Chatbot
        memberId={profile.memberId}
        memberName={[profile.firstName, profile.lastName].filter(Boolean).join(" ")}
      />
    </>
  );
}
