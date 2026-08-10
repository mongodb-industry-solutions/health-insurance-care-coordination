"use client";

import { useState } from "react";
import Header from "@/components/header/Header";
import MemberSelection from "@/components/memberSelection/MemberSelection";
import StoryCarousel from "@/components/storyCarousel/StoryCarousel";

export default function Home() {
  const [storyMember, setStoryMember] = useState(null);

  // TODO: route into the main app shell once that tab exists.
  const handleStoryFinish = () => {
    console.log("Entering demo as:", storyMember?.memberId);
    setStoryMember(null);
  };

  return (
    <main>
      <Header />
      <MemberSelection onStart={setStoryMember} />

      {storyMember && (
        <StoryCarousel member={storyMember} onFinish={handleStoryFinish} />
      )}
    </main>
  );
}
