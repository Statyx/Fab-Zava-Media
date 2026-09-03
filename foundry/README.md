# `foundry/` — Azure AI Foundry: project, connection, agents

The second half of the deploy. Everything here runs **after** the Fabric data agent is
published, and nothing here can be reordered above it.

| Module | Does |
|---|---|
| `foundry_common.py` | ARM + Agents data-plane helpers. Two api-versions, one of which is literally `v1` |
| `deploy_foundry_project.py` | resource group, AI Services account, project, model deployment |
| `deploy_foundry_connection.py` | the Fabric data agent connection, built from state GUIDs |
| `deploy_foundry_agents.py` | Zava-Media-Contracts (subordinate) + Zava-Media-Agent (supervisor), A2A wiring |
| `verify_foundry.py` | three routing probes + the answer contract, post-deploy |

## Order is not negotiable

```bash
python -m foundry.deploy_foundry_project
python -m foundry.deploy_foundry_connection
python -m foundry.deploy_foundry_agents
python -m foundry.verify_foundry
```

A connection can only point at a **published** Fabric artifact. Against a draft data
agent the call succeeds and the connection is useless: there is no stable answer
surface behind it. That is why `foundry_connection` sits after `data_agent` in
`deploy_all.py` and cannot be hoisted.

## Why the agent prompts are testable offline

The Azure SDK imports live *inside* the functions, not at module scope. That is
deliberate: it lets the test suite import the module and inspect the supervisor prompt
— that it forces a tool call, bounds its loop, relays figures rather than recomputing
them, and never describes itself — without an Azure credential in CI.

## Verifying

`python -m foundry.verify_foundry` is the only thing that proves routing actually
happens. A supervisor that answers plausibly from its own prompt looks identical to one
that queried the data agent, right up until someone in the room challenges the number.
