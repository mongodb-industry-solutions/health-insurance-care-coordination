"use client";

import Icon from "@leafygreen-ui/icon";
import InfoTip from "@/components/infoTip/InfoTip";
import { buildCostView, formatMoney, formatRange } from "@/lib/costPresenter";
import styles from "./CostEstimator.module.css";

const STATUS_GLYPH = {
  neutral: "InfoWithCircle",
  progress: "ClockWithArrow",
  success: "CheckmarkWithCircle",
  denied: "XWithCircle",
};

/** A share of a total, as a percentage a bar segment can use. */
const share = (value, total) =>
  total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;

/** A small section label with its explanation beside it. */
function Label({ children, tip }) {
  return (
    <h4 className={styles.label}>
      {children}
      {tip}
    </h4>
  );
}

function StatusBanner({ decision }) {
  return (
    <div className={`${styles.status} ${styles[`status_${decision.tone}`]}`}>
      {/* Not colour alone: the chip carries an icon and a word. */}
      <span className={styles.chip}>
        <Icon glyph={STATUS_GLYPH[decision.tone] ?? "InfoWithCircle"} size={12} />
        {decision.label}
      </span>
      <p className={styles.statusText}>{decision.text}</p>
      <InfoTip label="the request status" title="Where your request stands" align="end">
        This follows your prior authorization: not requested yet, in review, then approved,
        approved with limits, or denied. Cases the agents can&apos;t settle on their own go to a
        medical director.
      </InfoTip>
    </div>
  );
}

function RuleRow({ index, name, value, tiny, tip }) {
  return (
    <li className={styles.rule}>
      <span className={styles.ruleIndex} aria-hidden="true">
        {index}
      </span>
      <div className={styles.ruleBody}>
        <p className={styles.ruleName}>
          {name}
          {tip}
        </p>
        <p className={styles.tiny}>{tiny}</p>
      </div>
      <strong className={styles.ruleValue}>{value}</strong>
    </li>
  );
}

function HowItWorks({ sharing }) {
  const percent = sharing.coinsurance != null ? Math.round(sharing.coinsurance * 100) : null;
  let index = 0;

  return (
    <section className={styles.section}>
      <Label
        tip={
          <InfoTip label="how your share is worked out" title="How your share is worked out">
            Your plan sets the rules: you pay a deductible first, then a percentage of the rest,
            and never more than the yearly maximum.
          </InfoTip>
        }
      >
        How your share works
      </Label>
      <p className={styles.tiny}>The same three rules your plan applies to every claim.</p>

      <ol className={styles.rules}>
        {percent != null && sharing.deductible > 0 && (
          <RuleRow
            index={(index += 1)}
            name="Deductible"
            value={formatMoney(sharing.deductible)}
            tiny={`You pay the first ${formatMoney(sharing.deductible)} of care yourself.`}
            tip={
              <InfoTip label="deductible" title="Deductible">
                What you pay before the plan starts sharing costs. It resets every plan year.
                Your claims don&apos;t record how much you&apos;ve already met, so the estimate
                shows both cases.
              </InfoTip>
            }
          />
        )}
        {percent != null && (
          <RuleRow
            index={(index += 1)}
            name="Coinsurance"
            value={`${percent}%`}
            tiny={`After that you pay ${percent}% of the rest. The plan pays ${100 - percent}%.`}
            tip={
              <InfoTip label="coinsurance" title="Coinsurance">
                Your percentage of each covered cost once the deductible is paid. The plan pays
                the remainder.
              </InfoTip>
            }
          />
        )}
        {percent == null && sharing.copay != null && (
          <RuleRow
            index={(index += 1)}
            name="Copay"
            value={formatMoney(sharing.copay)}
            tiny="A flat amount you pay each time."
            tip={
              <InfoTip label="copay" title="Copay">
                A fixed fee per visit or fill, whatever the full price was.
              </InfoTip>
            }
          />
        )}
        {sharing.outOfPocketMax != null && (
          <RuleRow
            index={(index += 1)}
            name="Out-of-pocket max"
            value={formatMoney(sharing.outOfPocketMax)}
            tiny="The most you can pay in a year. After that, the plan pays in full."
            tip={
              <InfoTip label="out-of-pocket maximum" title="Out-of-pocket maximum">
                A yearly ceiling on what you pay for covered care. Your premium doesn&apos;t count
                toward it.
              </InfoTip>
            }
          />
        )}
      </ol>
    </section>
  );
}

function Estimate({ view }) {
  const { estimate, sharing, reference } = view;

  // No price on file: the rules are still true, so say them, but do not invent a figure.
  if (!estimate) {
    const rule =
      sharing.coinsurance != null
        ? `${Math.round(sharing.coinsurance * 100)}%${sharing.deductible ? ` after a ${formatMoney(sharing.deductible)} deductible` : ""}`
        : `a flat ${formatMoney(sharing.copay)} copay`;

    return (
      <section className={styles.section}>
        <Label tip={<InfoTip label="no price available">No approved claims for this therapy are on file yet, so there is nothing to price it from. Once one exists, a dollar estimate appears here.</InfoTip>}>
          Your share
        </Label>
        <p className={styles.headlineSmall}>You&apos;d pay {rule}</p>
        <p className={styles.tiny}>
          There&apos;s no reference price for this therapy yet, so no dollar amount is shown.
        </p>
      </section>
    );
  }

  const { price, low, high, parts, capApplied } = estimate;
  const planPays = price - high;
  const isRange = Math.round(low) !== Math.round(high);

  return (
    <section className={styles.section}>
      <Label
        tip={
          <InfoTip label="your estimated share" title="Your estimated share">
            The plan&apos;s rules applied to a typical price for this therapy. It&apos;s an
            estimate, not a bill and not a promise of coverage.
          </InfoTip>
        }
      >
        Your estimated share
      </Label>

      <p className={styles.headline}>{formatRange(low, high)}</p>
      <p className={styles.tiny}>
        of about {formatMoney(price)} for this therapy
        <InfoTip label="the reference price" title="Where the price comes from">
          Nothing in your plan lists a price, so this is the typical amount billed on{" "}
          {reference.count} approved {reference.count === 1 ? "claim" : "claims"} for the same
          therapy (the median). Other members&apos; claims, with no personal details.
        </InfoTip>
      </p>

      <div
        className={styles.bar}
        role="img"
        aria-label={`Of about ${formatMoney(price)}, the plan pays about ${formatMoney(planPays)} and you pay up to ${formatMoney(high)}.`}
      >
        <span className={styles.segPlan} style={{ width: `${share(planPays, price)}%` }} />
        <span className={styles.segCoins} style={{ width: `${share(parts.coinsurance ?? parts.copay ?? 0, price)}%` }} />
        {parts.deductible > 0 && (
          <span className={styles.segDeductible} style={{ width: `${share(parts.deductible, price)}%` }} />
        )}
      </div>

      <ul className={styles.legend}>
        <li>
          <span className={`${styles.swatch} ${styles.segPlan}`} aria-hidden="true" />
          Plan pays about <strong>{formatMoney(planPays)}</strong>
        </li>
        <li>
          <span className={`${styles.swatch} ${styles.segCoins}`} aria-hidden="true" />
          You pay {estimate.kind === "copay" ? "a copay of" : "coinsurance of about"}{" "}
          <strong>{formatMoney(parts.coinsurance ?? parts.copay ?? 0)}</strong>
        </li>
        {parts.deductible > 0 && (
          <li>
            <span className={`${styles.swatch} ${styles.segDeductible}`} aria-hidden="true" />
            Plus a deductible of <strong>{formatMoney(parts.deductible)}</strong>, only if
            you haven&apos;t met it yet
          </li>
        )}
      </ul>

      {isRange && (
        <p className={styles.tiny}>
          The lower figure assumes your deductible is already met; the higher assumes it isn&apos;t.
        </p>
      )}
      {capApplied && (
        <p className={styles.tiny}>
          Held down by your yearly out-of-pocket maximum: you can&apos;t pay more than{" "}
          {formatMoney(estimate.remaining)} more this year.
        </p>
      )}
    </section>
  );
}

function YearlyCeiling({ view }) {
  const { sharing, amountMet, estimate } = view;
  const max = sharing.outOfPocketMax;
  if (max == null) return null;

  const therapyShare = estimate ? estimate.high : 0;
  const left = Math.max(0, max - amountMet - therapyShare);

  return (
    <section className={styles.section}>
      <Label
        tip={
          <InfoTip label="your yearly ceiling" title="Your yearly ceiling">
            What you&apos;ve already owed this year, what this therapy could add, and how much
            room is left before the plan pays everything.
          </InfoTip>
        }
      >
        Your year at a glance
      </Label>
      <p className={styles.tiny}>The most you can pay in a year is {formatMoney(max)}.</p>

      <div
        className={styles.bar}
        role="img"
        aria-label={`Of your ${formatMoney(max)} yearly maximum, you have paid ${formatMoney(amountMet)}, this therapy could add up to ${formatMoney(therapyShare)}, leaving ${formatMoney(left)}.`}
      >
        <span className={styles.segSoFar} style={{ width: `${share(amountMet, max)}%` }} />
        {therapyShare > 0 && (
          <span className={styles.segCoins} style={{ width: `${share(therapyShare, max)}%` }} />
        )}
      </div>

      <ul className={styles.legend}>
        <li>
          <span className={`${styles.swatch} ${styles.segSoFar}`} aria-hidden="true" />
          Paid so far this year <strong>{formatMoney(amountMet)}</strong>
        </li>
        {estimate && (
          <li>
            <span className={`${styles.swatch} ${styles.segCoins}`} aria-hidden="true" />
            This therapy, up to <strong>{formatMoney(therapyShare)}</strong>
          </li>
        )}
        <li>
          <span className={`${styles.swatch} ${styles.segLeft}`} aria-hidden="true" />
          Room left <strong>{formatMoney(left)}</strong>
        </li>
      </ul>
    </section>
  );
}

function Stages({ view }) {
  const { stages, priorAuthRequired } = view;
  if (!stages.length) return null;
  const uncovered = stages.some((stage) => stage.covered === false);

  return (
    <section className={styles.section}>
      <Label
        tip={
          <InfoTip label="coverage by stage" title="Covered, stage by stage">
            A treatment is paid for in stages. A plan can cover some and not others. When a stage
            isn&apos;t covered, the request can still be approved, but only with limits.
          </InfoTip>
        }
      >
        What&apos;s covered, stage by stage
      </Label>
      <p className={styles.tiny}>
        {priorAuthRequired ? "Needs prior authorization, the request this platform reviews." : "No prior authorization needed."}
        {priorAuthRequired && (
          <InfoTip label="prior authorization" title="Prior authorization">
            Specialty therapies need the plan&apos;s approval before they&apos;re covered. An
            insurance agent checks your eligibility and coverage, a care agent reviews the
            clinical case, and a doctor decides anything the agents can&apos;t.
          </InfoTip>
        )}
      </p>

      <ol className={styles.stages}>
        {stages.map((stage) => (
          <li
            key={stage.id}
            className={`${styles.stage} ${stage.covered === false ? styles.stageOut : ""}`}
          >
            <span className={styles.stageIcon} aria-hidden="true">
              <Icon glyph={stage.covered === false ? "X" : "Checkmark"} size={12} />
            </span>
            <span className={styles.stageName}>{stage.name}</span>
            <span className={styles.stageNote}>
              {stage.covered === false ? "Not covered: you pay in full" : (stage.cost ?? "Covered")}
            </span>
          </li>
        ))}
      </ol>

      {uncovered && (
        <p className={styles.tinyWarn}>
          Stages that aren&apos;t covered are paid by you in full, and aren&apos;t in the
          estimate above.
        </p>
      )}
    </section>
  );
}

function Peers({ reference }) {
  if (!reference) return null;

  return (
    <section className={styles.section}>
      <Label
        tip={
          <InfoTip label="what other members paid" title="What members like you paid">
            Typical amounts (the median) on approved claims for this therapy. They&apos;re other
            members&apos; claims, shown as totals, so nobody can be identified.
          </InfoTip>
        }
      >
        What members like you paid
      </Label>

      <div className={styles.peers}>
        <div>
          <span className={styles.peerLabel}>Billed</span>
          <strong className={styles.peerValue}>{formatMoney(reference.price)}</strong>
        </div>
        {reference.memberOwed != null && (
          <div>
            <span className={styles.peerLabel}>Member paid</span>
            <strong className={styles.peerValue}>{formatMoney(reference.memberOwed)}</strong>
          </div>
        )}
      </div>
      <p className={styles.tiny}>
        Based on {reference.count} approved {reference.count === 1 ? "claim" : "claims"} for this
        therapy.
      </p>
    </section>
  );
}

const BLOCKED = {
  notListed: {
    title: "Your plan doesn't list this therapy for this condition",
    tiny: "A request would be stopped at the coverage check, before any doctor reviews it.",
  },
  excluded: {
    title: "Your plan doesn't cover this therapy",
    tiny: "This plan leaves out the tier it belongs to, so the plan wouldn't contribute.",
  },
  denied: {
    title: "This request was denied",
    tiny: "The plan won't pay for it as requested.",
  },
};

function Blocked({ view }) {
  const copy = BLOCKED[view.blockedReason];

  return (
    <section className={`${styles.section} ${styles.blocked}`}>
      <p className={styles.blockedTitle}>
        <Icon glyph="XWithCircle" size={16} />
        {copy.title}
        <InfoTip label="what this means" title="What this means" align="end">
          Eligibility and coverage problems are settled right away by the insurance agent. A
          denial that rests on the clinical case is always reviewed by a medical director first.
        </InfoTip>
      </p>
      <p className={styles.tiny}>{copy.tiny}</p>

      {view.fullPrice != null ? (
        <>
          <p className={styles.headlineSmall}>
            Without coverage you&apos;d pay about {formatMoney(view.fullPrice)}
          </p>
          <p className={styles.tiny}>
            The typical billed amount for this therapy.
            <InfoTip label="the full price" title="The full price">
              If the plan doesn&apos;t pay, the whole bill is yours. This is the typical billed
              amount on approved claims for the same therapy.
            </InfoTip>
          </p>
        </>
      ) : (
        <p className={styles.tiny}>There&apos;s no reference price on file for this therapy yet.</p>
      )}

      <p className={styles.tiny}>
        Want options? The Plan Comparison tool shows what the other plans cover.
      </p>
    </section>
  );
}

function Premium({ premium }) {
  if (!premium) return null;

  return (
    <section className={`${styles.section} ${styles.premium}`}>
      <div>
        <p className={styles.label}>
          Your premium
          <InfoTip label="your premium" title="Your premium">
            What you pay to keep the policy active, whether or not you use care. It&apos;s
            separate from the costs above and doesn&apos;t count toward the out-of-pocket
            maximum.
          </InfoTip>
        </p>
        <p className={styles.tiny}>Paid on a schedule, apart from any care you use.</p>
      </div>
      <strong className={styles.premiumValue}>
        {formatMoney(premium.perPayment)}
        {premium.perLabel ? <span className={styles.premiumUnit}> / {premium.perLabel}</span> : null}
        <span className={styles.premiumAnnual}>{formatMoney(premium.annual)} a year</span>
      </strong>
    </section>
  );
}

/**
 * Cost Estimator: what a therapy will cost *this* member.
 *
 * Takes the therapy their doctor ordered, the rules of their plan and what other
 * members were billed for the same therapy, and shows the member's likely share,
 * stage by stage. It follows the prior authorization too: once the case is decided
 * the tab says so, and a denial reads as a denial.
 *
 * @param {object} props.data  `{ policy, plan, claims, traces, precedent }` from useToolData.
 * @param {object} props.member  The loaded member document.
 */
export default function CostEstimator({ data, member }) {
  const view = buildCostView({ member, ...data });

  if (view.mode === "none") {
    return (
      <div className={styles.root}>
        <header className={styles.head}>
          <p className={styles.eyebrow}>Cost estimate</p>
          <h3 className={styles.title}>No treatment is being priced right now</h3>
          <p className={styles.tiny}>
            When a doctor proposes a treatment, its estimated cost to you appears here.
          </p>
        </header>

        {view.tiers.length > 0 && (
          <section className={styles.section}>
            <Label
              tip={
                <InfoTip label="how your plan shares costs" title="How your plan shares costs">
                  Standard care usually has a flat copay. Specialty care has a deductible, then
                  coinsurance, up to a yearly maximum.
                </InfoTip>
              }
            >
              How your plan shares costs
            </Label>
            <ul className={styles.tiers}>
              {view.tiers.map((tier) => (
                <li key={tier.name}>
                  <strong>{tier.name}</strong>
                  <span>{tier.line}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <Premium premium={view.premium} />
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <header className={styles.head}>
        <p className={styles.eyebrow}>
          Cost estimate
          <InfoTip label="the cost estimate" title="How this is worked out">
            Your plan&apos;s rules (deductible, coinsurance, yearly maximum) applied to what other
            members&apos; approved claims for this therapy were billed. It&apos;s an estimate,
            not a bill, and not a promise of coverage.
          </InfoTip>
        </p>
        <h3 className={styles.title}>{view.name}</h3>
        {view.diagnosisCode && (
          <p className={styles.tiny}>
            For {view.diagnosis ? `${view.diagnosis} (${view.diagnosisCode})` : `diagnosis ${view.diagnosisCode}`}
          </p>
        )}
      </header>

      <StatusBanner decision={view.decision} />

      {view.mode === "blocked" ? (
        <Blocked view={view} />
      ) : (
        <>
          <Estimate view={view} />
          <HowItWorks sharing={view.sharing} />
          <YearlyCeiling view={view} />
        </>
      )}

      <Stages view={view} />
      <Peers reference={view.reference} />
      <Premium premium={view.premium} />
    </div>
  );
}
