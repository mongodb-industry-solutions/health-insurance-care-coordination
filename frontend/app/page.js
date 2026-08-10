"use client";

import Header from "@/components/header/Header";
import MemberSelection from "@/components/memberSelection/MemberSelection";

export default function Home() {
  // TODO: route into the member dashboard once that tab exists.
  const handleStart = (member) => {
    console.log("Starting demo as:", member.memberId);
  };

  return (
    <main>
      <Header />
      <MemberSelection onStart={handleStart} />
    </main>
  );
}
