"use client";

import { useState } from "react";
import Header from "@/components/header/Header";
import MemberDashboard from "@/components/memberDashboard/MemberDashboard";
import MemberSelection from "@/components/memberSelection/MemberSelection";
import StoryCarousel from "@/components/storyCarousel/StoryCarousel";

export default function Home() {
  // The picked member, and whether their story is still showing over the page.
  const [member, setMember] = useState(null);
  const [storyOpen, setStoryOpen] = useState(false);

  const handleStart = (picked) => {
    setMember(picked);
    setStoryOpen(true);
  };

  const handleLogOut = () => {
    setMember(null);
    setStoryOpen(false);
  };

  if (member && !storyOpen) {
    return <MemberDashboard profile={member} onLogOut={handleLogOut} />;
  }

  return (
    <main>
      <Header />
      <MemberSelection onStart={handleStart} />

      {member && storyOpen && (
        <StoryCarousel member={member} onFinish={() => setStoryOpen(false)} />
      )}
    </main>
  );
}
