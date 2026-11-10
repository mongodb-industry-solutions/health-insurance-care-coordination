"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Header from "@/components/header/Header";
import styles from "./About.module.css";

/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */

const STATS = [
  { value: "2", label: "cooperating agents" },
  { value: "2", label: "databases, one cluster" },
  { value: "6", label: "workflow stages" },
  { value: "1", label: "shared audit trace" },
];

/** Diagram nodes. Coordinates are in the SVG's 900 x 440 viewBox. */
const NODES = {
  ui: {
    x: 330, y: 10, w: 240, h: 64, kind: "app",
    title: "Member workspace", sub: "Next.js",
    edges: ["ui-be"],
    detail: {
      heading: "Member workspace — Next.js",
      body: "Member dashboard, live authorization progress, decision tracing, medical director review and agent chat. The browser only ever talks to this app, which proxies /api/* to the backend, so no credential reaches the client.",
    },
  },
  be: {
    x: 330, y: 130, w: 240, h: 64, kind: "app",
    title: "Application backend", sub: "Python FastAPI",
    edges: ["ui-be", "be-ins", "be-care", "be-insdb", "be-clidb"],
    detail: {
      heading: "Application backend — Python FastAPI",
      body: "Starts and monitors cases, serves composed views of both databases, records the medical director's decision, seeds demo data and relays chat. It is the only component that holds both databases, and it reaches the agents through one OAuth service-account client.",
    },
  },
  ins: {
    x: 90, y: 250, w: 240, h: 64, kind: "agent",
    title: "Insurance Agent", sub: "Atlas Agent Engine",
    edges: ["be-ins", "ins-insdb"],
    detail: {
      heading: "Insurance Agent — Atlas Agent Engine",
      body: "Owns the administrative half: opening the case, eligibility, coverage, routing and closure. It reads members, policies, plans and claims, and has no access to clinical data.",
    },
  },
  care: {
    x: 570, y: 250, w: 240, h: 64, kind: "agent",
    title: "Care Coordination Agent", sub: "Atlas Agent Engine",
    edges: ["be-care", "care-clidb", "care-trace"],
    detail: {
      heading: "Care Coordination Agent — Atlas Agent Engine",
      body: "Owns the clinical half: matching the request to the record, classifying the treatment, reviewing trial history and refill gaps, applying step therapy and recommending a decision. It has no access to insurance data apart from writing its steps to the shared trace.",
    },
  },
  insdb: {
    x: 90, y: 370, w: 240, h: 56, kind: "db",
    title: "Insurance database", sub: "members · policies · plans · claims",
    edges: ["be-insdb", "ins-insdb", "trace-insdb"],
    detail: {
      heading: "Insurance database",
      body: "Members, policies, plans, claims, admin_reasoning and the shared audit_log trace. Business-key unique indexes keep lookups fast and prevent duplicates.",
    },
  },
  trace: {
    x: 360, y: 370, w: 180, h: 56, kind: "trace",
    title: "audit_log", sub: "shared trace",
    edges: ["care-trace", "trace-insdb"],
    detail: {
      heading: "audit_log — the shared authorization trace",
      body: "One document per case, holding the workflow stage, whose turn it is, administrative gates, step summaries, the outcome and the review. It is the only channel between the two agents and contains no diagnosis text.",
    },
  },
  clidb: {
    x: 570, y: 370, w: 240, h: 56, kind: "db",
    title: "Clinical database", sub: "profiles · fills · guidelines",
    edges: ["be-clidb", "care-clidb"],
    detail: {
      heading: "Clinical database",
      body: "Clinical profiles, pharmacy dispense history, versioned guidelines and clinical_reasoning. Only the backend and the Care Coordination Agent connect to it.",
    },
  },
};

const EDGES = {
  "ui-be": "M450 74 L450 130",
  "be-ins": "M400 194 L210 250",
  "be-care": "M500 194 L690 250",
  "ins-insdb": "M210 314 L210 370",
  "care-clidb": "M690 314 L690 370",
  "care-trace": "M640 314 L470 370",
  "trace-insdb": "M360 398 L330 398",
  "be-insdb": "M330 162 C30 162 30 398 90 398",
  "be-clidb": "M570 162 C870 162 870 398 810 398",
};

const STAGES = [
  {
    id: "OPENED", actor: "Insurance Agent", tone: "insurance",
    text: "The backend starts a case for a member. The Insurance Agent opens the trace.",
  },
  {
    id: "ADMIN_CLEARED", actor: "Insurance Agent", tone: "insurance",
    text: "Eligibility and coverage are checked. An administrative denial closes the case here.",
  },
  {
    id: "CLINICAL_RECOMMENDED", actor: "Care Coordination Agent", tone: "care",
    text: "The clinical record is matched, the treatment classified, trial history and refill gaps reviewed, step therapy applied, and a recommendation recorded with a confidence score.",
  },
  {
    id: "ROUTED", actor: "Insurance Agent", tone: "insurance",
    text: "The Insurance Agent routes the case: it is either closed or escalated for a person to decide.",
  },
  {
    id: "ESCALATED", actor: "Medical director", tone: "human",
    text: "A medical director reviews the case in the workspace. This is the only transition a person makes.",
  },
  {
    id: "CLOSED", actor: "Medical director", tone: "human",
    text: "The decision is recorded on the trace, and the claim and member summary reflect it.",
  },
];

const FEATURES = [
  {
    id: "documents", icon: "{ }", title: "Flexible documents",
    summary: "One document per case.",
    body: "An authorization case is a single audit_log document holding the stage, gates, step summaries, outcome and review. Both agents add to it without schema migrations or joins across tables, and the whole case reads back in one call.",
    where: "audit_log, admin_reasoning, clinical_reasoning",
  },
  {
    id: "atomic", icon: "⚛", title: "Atomic updates",
    summary: "Safe hand-offs between agents.",
    body: "Each stage transition is a compare-and-set on workflow.stage in a single document. A tool called at the wrong stage is refused, and two writers cannot overwrite each other, so the trace never tells two stories.",
    where: "workflow.stage, workflow.nextActor",
  },
  {
    id: "streams", icon: "≋", title: "Change streams",
    summary: "Live progress, no polling.",
    body: "The backend watches the trace collection and streams progress to the workspace as the agents write each step. Change streams need a replica set, which every Atlas cluster is.",
    where: "workflow/watcher.py",
  },
  {
    id: "isolation", icon: "⛨", title: "Data isolation",
    summary: "Least privilege, one cluster.",
    body: "Insurance and clinical data live in separate databases on the same cluster. Each agent connects to its own database, and the trace is the only shared record. The Insurance Agent cannot read clinical data, and the reverse.",
    where: "INSURANCE_DATABASE, CLINICAL_DATABASE",
  },
  {
    id: "indexes", icon: "⌗", title: "Business-key indexes",
    summary: "Fast, duplicate-free lookups.",
    body: "Unique indexes on memberId, policyId, planId, claimId and traceId keep every lookup off a collection scan and prevent two documents sharing a key. Everything joins on business keys, never on _id.",
    where: "python -m db.indexes",
  },
  {
    id: "memory", icon: "◈", title: "Agent memory on Atlas",
    summary: "Context across conversations.",
    body: "Atlas Agent Engine stores agent memory in MongoDB and embeds it with Voyage AI (voyage-4-large, 1,024 dimensions), so the agents can recall context between conversations and sessions.",
    where: "project-config.yaml · features.memory",
  },
];

const AUDIT_FLOW = [
  "Every step is written to the trace as it happens",
  "The agents' reasoning is stored beside it, in its own database",
  "The medical director's decision closes the same document",
  "A decision-tracing view in the workspace replays the whole case",
];

const COLLECTIONS = {
  insurance: ["members", "policies", "plans", "claims", "audit_log", "admin_reasoning"],
  clinical: ["clinical profiles", "dispense history", "guidelines", "clinical_reasoning"],
};

const STACK = [
  "Next.js 16", "React 19", "LeafyGreen UI", "FastAPI", "Python 3.13", "PyMongo",
  "uv", "LangGraph", "Atlas Agent Engine", "MongoDB Atlas", "Voyage AI",
];

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

/** Fades a block in once as it scrolls into view. Content stays visible without JS. */
function Reveal({ children, className = "", delay = 0, as: Tag = "div" }) {
  const ref = useRef(null);
  const [ready, setReady] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    setReady(true);
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      ref={ref}
      className={`${styles.reveal} ${className}`}
      data-ready={ready}
      data-visible={visible}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

function SectionHead({ eyebrow, title, lead }) {
  return (
    <Reveal className={styles.sectionHead}>
      <span className={styles.eyebrow}>{eyebrow}</span>
      <h2 className={styles.h2}>{title}</h2>
      <p className={styles.lead}>{lead}</p>
    </Reveal>
  );
}

/* ------------------------------------------------------------------ */
/* Sections                                                            */
/* ------------------------------------------------------------------ */

function ArchitectureDiagram() {
  const [active, setActive] = useState("be");
  const node = NODES[active];

  const select = (id) => setActive(id);
  const onKey = (event, id) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(id);
    }
  };

  return (
    <div className={styles.archWrap}>
      <div className={styles.diagramCard}>
        <svg
          viewBox="0 0 900 440"
          className={styles.diagram}
          role="group"
          aria-label="Solution architecture. Select a component for details."
        >
          {Object.entries(EDGES).map(([id, d]) => (
            <path
              key={id}
              d={d}
              className={`${styles.edge} ${node.edges.includes(id) ? styles.edgeActive : ""}`}
            />
          ))}

          {Object.entries(NODES).map(([id, n]) => (
            <g
              key={id}
              role="button"
              tabIndex={0}
              aria-pressed={active === id}
              aria-label={`${n.title}, ${n.sub}`}
              className={`${styles.node} ${styles[`node_${n.kind}`]} ${active === id ? styles.nodeActive : ""}`}
              onClick={() => select(id)}
              onKeyDown={(e) => onKey(e, id)}
              onMouseEnter={() => select(id)}
            >
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={n.kind === "db" ? 14 : 12} />
              <text x={n.x + n.w / 2} y={n.y + n.h / 2 - 4} className={styles.nodeTitle}>
                {n.title}
              </text>
              <text x={n.x + n.w / 2} y={n.y + n.h / 2 + 15} className={styles.nodeSub}>
                {n.sub}
              </text>
            </g>
          ))}
        </svg>
        <p className={styles.hint}>Hover or select a component to see its role.</p>
      </div>

      <aside className={styles.detailCard} aria-live="polite" key={active}>
        <span className={`${styles.detailTag} ${styles[`tag_${node.kind}`]}`}>
          {node.kind === "app" ? "Application" : node.kind === "agent" ? "Agent" : node.kind === "trace" ? "Shared record" : "Data"}
        </span>
        <h3 className={styles.detailTitle}>{node.detail.heading}</h3>
        <p className={styles.detailBody}>{node.detail.body}</p>
      </aside>
    </div>
  );
}

function StageWalkthrough() {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setIndex((i) => (i + 1) % STAGES.length), 3200);
    return () => clearInterval(timer);
  }, [playing]);

  const stage = STAGES[index];

  return (
    <div className={styles.flowCard}>
      <ol className={styles.stepper}>
        {STAGES.map((s, i) => (
          <li key={s.id} className={styles.stepItem}>
            <button
              type="button"
              className={`${styles.step} ${styles[`step_${s.tone}`]} ${i === index ? styles.stepActive : ""} ${i < index ? styles.stepDone : ""}`}
              onClick={() => {
                setIndex(i);
                setPlaying(false);
              }}
              aria-current={i === index ? "step" : undefined}
            >
              <span className={styles.stepNum}>{i + 1}</span>
              <span className={styles.stepName}>{s.id.replace("_", " ")}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className={styles.flowBody} key={stage.id}>
        <span className={`${styles.actor} ${styles[`actor_${stage.tone}`]}`}>{stage.actor}</span>
        <p className={styles.flowText}>{stage.text}</p>
      </div>

      <div className={styles.flowFooter}>
        <p className={styles.flowNote}>
          Every write is a compare-and-set on the current stage. A refused call means the action did not
          happen, and the agents say so rather than report an outcome that was not recorded.
        </p>
        <button type="button" className={styles.ghostBtn} onClick={() => setPlaying((p) => !p)}>
          {playing ? "Pause" : "Play"}
        </button>
      </div>
    </div>
  );
}

function FeatureExplorer() {
  const [activeId, setActiveId] = useState(FEATURES[0].id);
  const active = FEATURES.find((f) => f.id === activeId);

  return (
    <div className={styles.featureLayout}>
      <div className={styles.featureList} role="tablist" aria-label="MongoDB features">
        {FEATURES.map((f) => (
          <button
            key={f.id}
            role="tab"
            type="button"
            aria-selected={f.id === activeId}
            className={`${styles.featureTab} ${f.id === activeId ? styles.featureTabActive : ""}`}
            onClick={() => setActiveId(f.id)}
          >
            <span className={styles.featureIcon} aria-hidden="true">{f.icon}</span>
            <span>
              <span className={styles.featureTabTitle}>{f.title}</span>
              <span className={styles.featureTabSummary}>{f.summary}</span>
            </span>
          </button>
        ))}
      </div>

      <div className={styles.featurePanel} role="tabpanel" key={active.id}>
        <span className={styles.featureBigIcon} aria-hidden="true">{active.icon}</span>
        <h3 className={styles.detailTitle}>{active.title}</h3>
        <p className={styles.detailBody}>{active.body}</p>
        <p className={styles.where}>
          <span>In this demo</span>
          <code>{active.where}</code>
        </p>
      </div>
    </div>
  );
}

function DataModel() {
  return (
    <div className={styles.dataGrid}>
      <div className={`${styles.dbCard} ${styles.dbInsurance}`}>
        <h3 className={styles.dbTitle}>Insurance database</h3>
        <p className={styles.dbWho}>Backend · Insurance Agent</p>
        <ul className={styles.chips}>
          {COLLECTIONS.insurance.map((c) => (
            <li key={c} className={c === "audit_log" ? styles.chipTrace : styles.chip}>{c}</li>
          ))}
        </ul>
      </div>

      <div className={styles.bridge} aria-hidden="true">
        <span className={styles.bridgeLine} />
        <span className={styles.bridgeLabel}>audit_log</span>
        <span className={styles.bridgeLine} />
      </div>

      <div className={`${styles.dbCard} ${styles.dbClinical}`}>
        <h3 className={styles.dbTitle}>Clinical database</h3>
        <p className={styles.dbWho}>Backend · Care Coordination Agent</p>
        <ul className={styles.chips}>
          {COLLECTIONS.clinical.map((c) => (
            <li key={c} className={styles.chip}>{c}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function About() {
  return (
    <>
      {/* The header sits inside the hero's background so the two read as one surface. */}
      <div className={styles.top}>
      <Header navItems={[]} action={{ label: "Go back to Demo", href: "/", back: true }} />
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <Reveal>
            <span className={styles.eyebrow}>About this demo</span>
            <h1 className={styles.h1}>
              Two agents, one auditable trace, and a person who makes the final call.
            </h1>
            <p className={styles.heroLead}>
              Prior authorization needs administrative and clinical expertise that live in different
              systems. This demo splits the work between two cooperating agents on Atlas Agent Engine,
              keeps their data separate on one MongoDB Atlas cluster, and records every step so a case
              can be explained afterwards.
            </p>
            <div className={styles.heroActions}>
              <Link href="/" className={styles.primaryBtn}>Try the demo</Link>
              <a href="#architecture" className={styles.secondaryBtn}>Explore the architecture</a>
            </div>
          </Reveal>

          <Reveal delay={120}>
            <dl className={styles.stats}>
              {STATS.map((s) => (
                <div key={s.label} className={styles.stat}>
                  <dt className={styles.statValue}>{s.value}</dt>
                  <dd className={styles.statLabel}>{s.label}</dd>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>
      </section>
      </div>

      <section className={styles.section}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="The problem"
            title="Evidence in two places, a decision that must be explainable"
            lead="Reviewers gather administrative and clinical evidence by hand, which is slow and hard to apply consistently. It is just as hard to explain afterwards why a case was approved or denied."
          />
          <div className={styles.cardRow}>
            {[
              ["Administrative", "Is the member eligible, and is the treatment covered under the plan?"],
              ["Clinical", "Does the member's history meet the guideline, and did earlier therapies really fail?"],
              ["Accountable", "Who decided, on what evidence, and in which order did it happen?"],
            ].map(([title, text], i) => (
              <Reveal key={title} delay={i * 90} className={styles.infoCard}>
                <h3 className={styles.cardTitle}>{title}</h3>
                <p className={styles.cardText}>{text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section id="architecture" className={`${styles.section} ${styles.tinted}`}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Architecture"
            title="Four components, each with a clear job"
            lead="The workspace talks only to the backend. The backend invokes two deployed agents. Each agent works against its own database, and the trace is the one record they share."
          />
          <Reveal>
            <ArchitectureDiagram />
          </Reveal>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Authorization flow"
            title="A stage machine that says whose turn it is"
            lead="A case moves through six stages stored on the trace. The agents make every transition up to escalation, and a medical director makes the last one."
          />
          <Reveal>
            <StageWalkthrough />
          </Reveal>
        </div>
      </section>

      <section id="why-mongodb" className={`${styles.section} ${styles.dark}`}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Why MongoDB"
            title="Where MongoDB shines"
            lead="The same cluster holds the operational data, the audit trail and the agents' runtime state."
          />
          <Reveal>
            <FeatureExplorer />
          </Reveal>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Data model"
            title="Separate databases, one shared record"
            lead="Insurance and clinical data live in different databases on one cluster. Everything joins on business keys, and the trace is the only bridge between the two sides."
          />
          <Reveal>
            <DataModel />
          </Reveal>
        </div>
      </section>

      <section className={`${styles.section} ${styles.tinted}`}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Governance"
            title="Every decision leaves a record"
            lead="Atlas Agent Engine runs and governs the agents. It does not replace the insurer's policy or the reviewer's authority: the agents recommend, and a person decides."
          />
          <ul className={styles.auditList}>
            {AUDIT_FLOW.map((item, i) => (
              <Reveal as="li" key={item} delay={i * 80} className={styles.auditItem}>
                <span className={styles.auditNum}>{i + 1}</span>
                {item}
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <SectionHead
            eyebrow="Tech stack"
            title="Built with"
            lead="Atlas Agent Engine is in Public Preview and intended for evaluation and prototyping."
          />
          <Reveal>
            <ul className={styles.stack}>
              {STACK.map((t) => (
                <li key={t} className={styles.stackChip}>{t}</li>
              ))}
            </ul>
          </Reveal>
          <Reveal className={styles.cta}>
            <h2 className={styles.ctaTitle}>See it work on a real case</h2>
            <Link href="/" className={styles.primaryBtn}>Open the demo</Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
