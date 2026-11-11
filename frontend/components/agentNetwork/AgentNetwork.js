"use client";

import Icon from "@leafygreen-ui/icon";
import { AGENT_LABELS, agentKeyOf } from "@/lib/processPresenter";
import styles from "./AgentNetwork.module.css";

/**
 * Schematic of who is talking to whom: the member, the two agents, and the
 * records behind them.
 *
 * Built as an SVG connector layer with the node tiles as HTML on top. That split
 * is deliberate — the curves, the marching dashes and the travelling packets are
 * things SVG does properly, while the tiles want real text rendering and icons.
 * Both layers share one coordinate space (see NODES, in viewBox units), so the
 * container's aspect ratio is pinned to the viewBox and the two stay registered.
 */

/** Shared coordinate space for both layers. */
const VIEW = { width: 320, height: 200 };

const NODES = {
  user: { x: 36, y: 100, icon: "PersonWithLock", label: "Member", caption: "request" },
  insurance: {
    x: 160,
    y: 44,
    icon: "Sparkle",
    label: AGENT_LABELS.insurance,
    caption: "gates & routing",
    // Labelled above, so its caption stays clear of the wires below it.
    above: true,
  },
  care_coordination: {
    x: 160,
    y: 156,
    icon: "Sparkle",
    label: AGENT_LABELS.care_coordination,
    caption: "clinical review",
  },
  mongo: { x: 284, y: 100, icon: "Database", label: "MongoDB", caption: "records & audit" },
};

/**
 * The four links, drawn centre to centre — the node tiles are opaque and sit
 * over the endpoints, so the curves read as meeting them.
 */
const LINKS = [
  { id: "user-insurance", agent: "insurance", d: "M36,100 C92,100 104,44 160,44" },
  { id: "user-care", agent: "care_coordination", d: "M36,100 C92,100 104,156 160,156" },
  { id: "insurance-db", agent: "insurance", d: "M160,44 C216,44 228,100 284,100" },
  { id: "care-db", agent: "care_coordination", d: "M160,156 C216,156 228,100 284,100" },
];

/** Two packets per link, offset in time so the flow looks continuous. */
const PACKET_DELAYS = ["0s", "0.8s"];

/**
 * @param {"insurance"|"care_coordination"|null} props.activeAgent  Whoever holds
 *   the case right now. Null leaves the diagram at rest.
 */
export default function AgentNetwork({ activeAgent = null }) {
  const active = agentKeyOf(activeAgent);

  return (
    <section className={styles.card} aria-label="Agent network">
      <header className={styles.header}>
        <h3 className={styles.heading}>Agent network</h3>
        <span className={`${styles.state} ${active ? styles.stateLive : ""}`}>
          {active ? `${NODES[active]?.label ?? "Agent"} working` : "idle"}
        </span>
      </header>

      <div
        className={styles.stage}
        style={{ aspectRatio: `${VIEW.width} / ${VIEW.height}` }}
      >
        <svg
          className={styles.wires}
          viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            {/* Literal stops: `stop-color` does not reliably resolve a CSS
                custom property across browsers. Mirrors --color-green-soft
                and --color-green. */}
            <linearGradient id="agent-net-flow" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#1a7a5e" />
              <stop offset="100%" stopColor="#00684a" />
            </linearGradient>
            {LINKS.map((link) => (
              <path key={link.id} id={`path-${link.id}`} d={link.d} />
            ))}
          </defs>

          {LINKS.map((link) => {
            const live = active === link.agent;

            return (
              <g key={link.id}>
                {/* The link at rest, always drawn, so the topology is legible. */}
                <path className={styles.wireBase} d={link.d} />

                {live && (
                  <>
                    <path className={styles.wireFlow} d={link.d} />
                    {PACKET_DELAYS.map((delay) => (
                      <circle
                        key={delay}
                        className={styles.packet}
                        r="2.6"
                      >
                        <animateMotion
                          dur="1.6s"
                          begin={delay}
                          repeatCount="indefinite"
                          rotate="auto"
                        >
                          <mpath href={`#path-${link.id}`} />
                        </animateMotion>
                      </circle>
                    ))}
                  </>
                )}
              </g>
            );
          })}
        </svg>

        {Object.entries(NODES).map(([key, node]) => (
          <Node
            key={key}
            node={node}
            active={
              key === active || (key === "mongo" && Boolean(active))
            }
            muted={key === "user"}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * Centred on its coordinate: the tile is the positioned box and the labels hang
 * off it absolutely, so text length can never pull a node off its wire.
 */
function Node({ node, active, muted }) {
  return (
    <div
      className={styles.node}
      style={{
        left: `${(node.x / VIEW.width) * 100}%`,
        top: `${(node.y / VIEW.height) * 100}%`,
      }}
    >
      <span
        className={`${styles.tile} ${active ? styles.tileActive : ""} ${
          muted ? styles.tileMuted : ""
        }`}
      >
        <Icon glyph={node.icon} size={18} />
      </span>

      <span
        className={`${styles.meta} ${node.above ? styles.metaAbove : ""}`}
      >
        <span className={styles.label}>{node.label}</span>
        <span className={styles.caption}>{node.caption}</span>
      </span>
    </div>
  );
}
