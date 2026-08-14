/**
 * Narrative shown in the story carousel after a member is picked, keyed by
 * `memberId` so it lines up with MEMBERS in `./members.js`.
 *
 * Each entry is just a `cards` array — the carousel renders whatever it finds,
 * so the number of cards per member is free to change. A card's `closingLine`
 * is optional and gets the pull-quote treatment when present.
 */

const CLOSING_LINE = "What if there was a way to turn all that into minutes?";

export const MEMBER_STORIES = {
  // Maria Reyes — the canonical clean approval, with one explainable gap.
  "MBR-2026-44109": {
    cards: [
      {
        eyebrow: "MEET MARIA",
        title: "Meet Maria!",
        body: "Maria is a school librarian in Illinois. She has lived with rheumatoid arthritis since her diagnosis, and she also manages high blood pressure. Her mornings are stiff, her hands ache by the end of a shelving shift, and she has learned to plan her week around how her joints feel.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "For seven months Maria took methotrexate exactly as prescribed, and it simply did not control her disease. There is one gap in her pharmacy record: a ten-day pause around day ninety, when her rheumatologist held the drug during a respiratory infection. On paper it looks like she stopped. In reality, she never did.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "Dr. Patel has requested secukinumab, a specialty therapy her plan covers. Everything needed for a decision already exists — the trial, the outcome, the clinical reason for that ten-day hold — but it is scattered across pharmacy claims, visit notes and plan documents. Normally, someone spends days assembling it, and Maria waits.",
        closingLine: CLOSING_LINE,
      },
    ],
  },

  // Robert Chen — clean approval, nothing to explain.
  "MBR-2026-51882": {
    cards: [
      {
        eyebrow: "MEET ROBERT",
        title: "Meet Robert!",
        body: "Robert supervises a warehouse floor in Texas, a job that runs on his feet and his hands. Psoriatic arthritis has made both harder. He has been careful, consistent and patient with his treatment, and he would very much like to stop negotiating with his own knees.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "Robert completed eight uninterrupted months of methotrexate. No missed refills, no pauses, no ambiguity in his record. The response was still inadequate, which is exactly the situation step therapy is designed to identify before moving a member to a specialty drug.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "Dr. Okafor has requested adalimumab. This case is as clean as prior authorization gets: the trial is documented, the plan covers the tier, the guidelines are satisfied. And yet it still sits in the same queue as every complicated case, waiting for a human to confirm what the record already says.",
        closingLine: CLOSING_LINE,
      },
    ],
  },

  // Aisha Bello — genuinely ambiguous, routed to a medical director.
  "MBR-2026-60417": {
    cards: [
      {
        eyebrow: "MEET AISHA",
        title: "Meet Aisha!",
        body: "Aisha is a graphic designer in New York living with Crohn's disease. Her case has never been textbook — her presentation is atypical, and her symptoms have not followed the tidy arc the guidelines describe. She has learned to explain herself carefully to every new clinician.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "Six months on azathioprine produced a partial response: not the failure that clearly justifies escalation, not the success that would settle the question. This is the grey zone, and no amount of re-reading her chart turns it into a black-and-white answer.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "Dr. Nguyen has requested ustekinumab. This decision genuinely belongs to a medical director — that is the right outcome, not a failure of the system. But the director should receive a case that is already gathered, summarized and evidenced, instead of spending an afternoon building that picture from scratch.",
        closingLine: CLOSING_LINE,
      },
    ],
  },

  // David Thompson — step therapy not met.
  "MBR-2026-73305": {
    cards: [
      {
        eyebrow: "MEET DAVID",
        title: "Meet David!",
        body: "David is an accountant in Illinois, recently enrolled, recently diagnosed with rheumatoid arthritis. He is early in his treatment journey and understandably impatient — the pain is real now, and the process ahead of him is measured in months.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "David has been on methotrexate for three months. His response has been inadequate, but three months is short of the trial his plan's guidelines require before a specialty therapy can be approved. The clinical picture is not wrong; it is incomplete.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "Dr. Patel has requested secukinumab, and the honest answer today is not yet. David deserves that answer quickly, with the reasoning spelled out and the path forward made explicit — not weeks of silence followed by a denial letter he has to decode alone.",
        closingLine: CLOSING_LINE,
      },
    ],
  },

  // Grace Kim — clinically fine, benefit does not cover the tier.
  "MBR-2026-88214": {
    cards: [
      {
        eyebrow: "MEET GRACE",
        title: "Meet Grace!",
        body: "Grace drives a school bus in Illinois. Rheumatoid arthritis makes an early start and a long steering shift into something she has to brace for. Clinically, her case looks a great deal like Maria's.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "Grace completed seven months of methotrexate with an inadequate response — step therapy fully satisfied. By every clinical measure she qualifies for the next line of treatment. Her obstacle is not medical at all.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "The therapy Dr. Patel requested sits in the specialty tier, and Grace's standard plan does not cover that tier. This is an administrative answer, not a clinical one, and it is knowable in seconds from her plan documents. Instead it often surfaces at the very end, after a full medical review that was never the deciding factor.",
        closingLine: CLOSING_LINE,
      },
    ],
  },

  // Frank Alvarez — coverage lapsed before the request.
  "MBR-2026-90733": {
    cards: [
      {
        eyebrow: "MEET FRANK",
        title: "Meet Frank!",
        body: "Frank is an electrician in California with psoriatic arthritis. His hands are his livelihood, and he has done everything asked of him clinically — which makes what happened next particularly frustrating.",
      },
      {
        eyebrow: "THE ROAD SO FAR",
        title: "The Road So Far",
        body: "Eight months of methotrexate, an inadequate response, a clear case for escalation. On the clinical axis alone, Frank's request would sail through. But his coverage ended on May 31, 2026, before this request was ever filed.",
      },
      {
        eyebrow: "THE CURRENT SITUATION",
        title: "The Current Situation",
        body: "Dr. Ibrahim requested adalimumab for a member who is no longer eligible. Every hour spent reviewing the clinical merits is an hour that changes nothing, and Frank does not learn the one fact that actually matters — that he needs to fix his enrollment — until the very end.",
        closingLine: CLOSING_LINE,
      },
    ],
  },
};

/** Story for a member id, or null when none is authored yet. */
export function getMemberStory(memberId) {
  return MEMBER_STORIES[memberId] ?? null;
}
