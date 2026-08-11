"use client";

import { useState } from "react";
import AppHeader from "@/components/appHeader/AppHeader";
import DetailPanel from "@/components/detailPanel/DetailPanel";
import OtherTools from "@/components/otherTools/OtherTools";
import PatientIdentityCard from "@/components/patientIdentityCard/PatientIdentityCard";
import PendingActionsZone from "@/components/pendingActionsZone/PendingActionsZone";
import ToolDrawer from "@/components/toolDrawer/ToolDrawer";
import { toPendingActions } from "@/lib/memberPresenter";
import { useMemberDashboard } from "./useMemberDashboard";
import styles from "./MemberDashboard.module.css";

/**
 * Main tab: patient context on the left, actions and tools on the right.
 *
 * @param {object} props.profile  The selected MEMBERS entry (avatar, names).
 * @param {() => void} props.onLogOut
 */
export default function MemberDashboard({ profile, onLogOut }) {
  const { member, loading, error, startingActionId, startProcess } =
    useMemberDashboard(profile.memberId);

  const [openTool, setOpenTool] = useState(null);

  // TODO: point at the real settings route once it exists.
  const handleOpenSettings = () => console.log("Open settings");

  return (
    <>
      <AppHeader onLogOut={onLogOut} onOpenSettings={handleOpenSettings} />

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
              startingActionId={startingActionId}
              onStartProcess={startProcess}
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
    </>
  );
}
