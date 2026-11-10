# Care Coordination Agent

The clinical half of the prior-authorization demo, built with the Atlas Agent Engine SDK on LangGraph. After the Insurance Agent has cleared a case administratively, this agent assesses the request against the member's clinical record and recommends a decision. It never opens, routes or closes a case, and it has no access to insurance data (eligibility, policies, plans, claims).

It works together with the [Insurance Agent](../insurance-coordination-health-insurance/README.md). The two share only one record, the authorization trace (`audit_log`), whose `workflow.stage` says whose turn it is.

## What it does

The agent owns steps 3–7 of the process, as one strictly ordered sequence. It starts by reading the open case, which tells it the proposed treatment and the trace to write to. Each step is recorded on the trace with a memory type and a confidence score.

| Step | Memory type | What the agent does |
|---|---|---|
| 3. Match | semantic | Confirms the requested therapy corresponds to a diagnosis actually coded on the member, and flags any mismatch with the physician's stated diagnosis. |
| 4. Classify | taxonomic | Classifies the treatment against the guideline: tier, prior-auth and step-therapy requirements, confidence threshold. |
| 5. Trial history | episodic | Reviews how long the member really took the required therapy, using pharmacy fills, and resolves refill gaps explained by documented notes. |
| 6. Step therapy | procedural | Applies the guideline's step-therapy criteria. |
| 7. Recommend | | Computes an aggregate confidence and proposes `approved`, `approved_restricted` or `denied`, then records it. The stage becomes `CLINICAL_RECOMMENDED`. |

This is a **recommendation only**. The confidence figure comes from a deterministic tool, not from the model, because the Insurance Agent's routing keys off it. If a recording call fails, the agent stops rather than produce reasoning that was not saved.

## Tools

| Group | Tools |
|---|---|
| Lookups | `list_members`, `get_member_clinical_context`, `get_open_case`, `get_member_authorizations`, `get_applicable_guideline` |
| Reasoning (steps 3–6) | `match_clinical_concept`, `classify_treatment`, `review_trial_history`, `detect_refill_gaps`, `resolve_refill_gap`, `evaluate_step_therapy` |
| Recommendation (step 7) | `compute_recommendation`, `record_reasoning_step`, `record_recommendation` |
| Memory and utility | `get_current_date`, `save_user_info`, `recall_user_info` |

The tool order is defined in `system_message.py`, not in the graph.

## Data access

| Database | Access | Contents |
|---|---|---|
| **Clinical** (`MONGODB_DATABASE`) | Read, and writes its own reasoning | Clinical profiles, pharmacy dispense history, versioned guidelines, `clinical_reasoning` |
| **Insurance** (`AUDIT_DATABASE`) | One collection only: `audit_log` | The shared authorization trace |

Records join on business keys (`memberId`, `traceId`, `guidelineId`), never on `_id`.

## Set it up

You need the `agentengine` CLI installed and authenticated, a MongoDB Atlas cluster, and an LLM API key. The agent uses `gpt-5.4-mini`, set in `src/agent_care_coordination_health_insurance/llm.py`.

**1. Configure.** Copy the example file and fill it in with your own values:

```bash
cp env.example .env
```

| Variable | Meaning |
|---|---|
| `MONGODB_URI` | Atlas connection string |
| `MONGODB_DATABASE` | The **clinical** database. Use the same name as the backend's `CLINICAL_DATABASE`. |
| `AUDIT_DATABASE` | The **insurance** database. Use the same name as the backend's `INSURANCE_DATABASE`. |
| `LLM_API_KEY` | Credential for the LLM client |
| `VOYAGE_API_KEY` | Needed because memory is enabled (`features.memory: true` in `agent.yaml`) |

Load the demo data first, from the repository root (see the [main README](../../../README.md#5-install-create-indexes-and-seed)).

**2. Run locally (optional).**

```bash
agentengine dev up      # playground at http://localhost:3000
agentengine dev down
```

The playground is pinned to port 3000. Stop one agent's stack before starting the other's, or change `services.playground.port` in `dev.yaml`. The agent needs an open case, so for a full test start one from the demo, or run the Insurance Agent first.

**3. Deploy.**

```bash
agentengine auth login
agentengine init
agentengine secret set LLM_API_KEY --workspace-scope
agentengine secret set VOYAGE_API_KEY --workspace-scope
agentengine build
agentengine deploy
```

Keep the project ID and workspace ID for the backend's `AAE_PROJECT_ID` and `CARE_AGENT_WORKSPACE_ID`. Memory extraction also uses project-level secrets; see [`project-config.yaml`](../../project-config.yaml).

`agent.yaml` sets the entry point (`agent_care_coordination_health_insurance.main:app`), the feature flags, the tool list and the outbound `network.egress` allow-list. If you switch LLM provider or gateway, update the egress entry to match.

Do not commit `.env` files. Deployed agents read secrets from the platform secret store.
