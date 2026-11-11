# Insurance Agent

The administrative half of the prior-authorization demo, built with the Atlas Agent Engine SDK on LangGraph. It opens a case, checks eligibility and coverage, and later routes and closes the case. It never performs clinical reasoning and has no access to clinical data.

It works together with the [Care Coordination Agent](../care-coordination-health-insurance/README.md). The two share only one record, the authorization trace (`audit_log`), whose `workflow.stage` says whose turn it is.

## What it does

The agent's work happens in two phases, run as separate sessions with the Care Coordination Agent's turn in between.

| Phase | Steps | What the agent does |
|---|---|---|
| **A. Open and clear** | 0–2 | Opens the trace (`OPENED`), verifies the policy was active on the service date, checks that the plan covers the treatment, then clears the gates (`ADMIN_CLEARED`) and hands the case over. |
| **B. Route and close** | 8–9 | Once a clinical recommendation exists, asks the backend whether it may close the case or must escalate it, then closes it or escalates it, and updates the claim. |

The opening message from the backend is the agent's only source for the request: member ID, action ID, therapy, diagnosis code, referring physician, date of service and, when known, the billed amount.

**Bounded authority.** Routing is decided by the backend, not by the model. The agent may close a case itself only for:
- a factual administrative outcome (`eligibility_lapsed` or `benefit_exclusion`), or
- an approval whose confidence meets the guideline threshold.

Denials, pending recommendations and low-confidence recommendations go to a medical director. Every write is checked against the current stage, and a refused call means nothing was recorded.

## Tools

| Group | Tools |
|---|---|
| Lookups | `get_member_by_id`, `get_policy_by_id`, `get_plan_by_id`, `get_audit_trace`, `find_open_case`, `list_all_members`, `list_all_policies`, `list_all_plans`, `list_all_claims`, `list_all_audit_traces` |
| Gates (steps 0–2) | `create_audit_trace`, `verify_eligibility_on_date`, `check_treatment_coverage`, `append_reasoning_step`, `clear_administrative_gates` |
| Claims | `create_claim`, `update_claim_status` |
| Routing and closure (steps 8–9) | `route_decision`, `close_administrative_determination`, `close_authorization` |
| Memory and utility | `get_current_date`, `save_user_info`, `recall_user_info` |

The tool order is defined in `system_message.py`, not in the graph.

## Data access

One database only: the **insurance** database (`MONGODB_URI` and `MONGODB_DATABASE`).

Collections: `members`, `policies`, `plans`, `claims`, `audit_log` and `admin_reasoning`. Records join on business keys (`memberId`, `policyId`, `planId`, `claimId`, `traceId`), never on `_id`.

## Set it up

You need the `agentengine` CLI installed and authenticated, a MongoDB Atlas cluster, and an LLM API key. The agent uses `gpt-5.4`, set in `src/agent_insurance_coordination_health_insurance/llm.py`.

**1. Configure.** Copy the example file and fill it in with your own values:

```bash
cp env.example .env
```

| Variable | Meaning |
|---|---|
| `MONGODB_URI` | Atlas connection string |
| `MONGODB_DATABASE` | The insurance database. Use the same name as the backend's `INSURANCE_DATABASE`. |
| `LLM_API_KEY` | Credential for the LLM client |
| `VOYAGE_API_KEY` | Needed because memory is enabled (`features.memory: true` in `agent.yaml`) |

Load the demo data first, from the repository root (see the [main README](../../../README.md#5-install-create-indexes-and-seed)).

**2. Run locally (optional).**

```bash
agentengine dev up      # playground at http://localhost:3000
agentengine dev down
```

The playground is pinned to port 3000. Stop one agent's stack before starting the other's, or change `services.playground.port` in `dev.yaml`.

**3. Deploy.**

```bash
agentengine auth login
agentengine init
agentengine secret set LLM_API_KEY --workspace-scope
agentengine secret set VOYAGE_API_KEY --workspace-scope
agentengine build
agentengine deploy
```

Keep the project ID and workspace ID for the backend's `AAE_PROJECT_ID` and `INSURANCE_AGENT_WORKSPACE_ID`. Memory extraction also uses project-level secrets; see [`project-config.yaml`](../../project-config.yaml).

`agent.yaml` sets the entry point (`agent_insurance_coordination_health_insurance.main:app`), the feature flags, the tool list and the outbound `network.egress` allow-list. If you switch LLM provider or gateway, update the egress entry to match.

Do not commit `.env` files. Deployed agents read secrets from the platform secret store.
