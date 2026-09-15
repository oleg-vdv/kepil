# Kepil

<!-- mcp-name: io.github.oleg-vdv/kepil -->

[![PyPI](https://img.shields.io/pypi/v/kepil?color=1F5C4E)](https://pypi.org/project/kepil/)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-1F5C4E)](LICENSE)

**Accountability layer for AI agents.** Give every agent a passport, put every
action through one gate, and keep a log that cannot be rewritten afterwards.

> 53% of organisations have had an AI agent exceed its intended permissions.
> 48% of agents in production run with no monitoring at all. Only 22% treat an
> agent as an entity with its own identity.
> — Cloud Security Alliance and State of AI Agent Security, 2026

Kepil is what the other 78% are missing: identity, mandate, enforcement,
evidence — and the part nobody else does, **undo**.

```bash
pip install kepil
python -m kepil.admin        # http://localhost:7317
```

Русская версия: [README.ru.md](README.ru.md)

---

## What it does

**Passport.** Every agent version gets an immutable card: who built it, who runs
it, what it does, what it will *never* do, its risk class, its autonomy class,
its limits, and when its risks are due for review. A new version is a new card;
the old one is kept forever.

**Mandate.** A machine-readable power of attorney for one job: allowed actions,
allowed systems, spending limits, a validity window, and which action types must
be confirmed by a human. Anything not explicitly allowed is refused.

**Gate.** The single point through which an agent touches the outside world.
Every action is checked against the mandate *before* a model is even called.
Fail-closed: any error inside the check means refusal, never a pass.

**Journal.** Append-only JSONL where every record carries the hash of the one
before it. Editing or deleting a record is detectable — by anyone, using an
independent implementation:

```bash
npx proofbyte-agent-trace verify data/journal.jsonl
```

**Undo.** The journal is a graph of actions, and every profession declares its
compensating action. Kepil walks that graph backwards and stops honestly at the
first step that cannot be undone. Agent platforms record what happened; this one
puts it back.

**Confirmations on your phone.** Irreversible actions arrive in Telegram with
two buttons — approve or return — so being accountable does not mean sitting at
a laptop.

## Use it from any MCP client

Kepil ships an MCP server, so an editor, an assistant or another agent can work
through it — and every action still passes the same gate into the same journal.

```json
{
  "mcpServers": {
    "kepil": { "command": "python", "args": ["-m", "kepil.mcp"] }
  }
}
```

Seven tools: list professions, create an order, run a step, read order status,
see what is waiting for a human, verify the journal, read an agent passport.

**One tool is deliberately missing: confirmation.** If a model could approve an
irreversible action, the human would drop out of the chain and the whole design
would be pointless. The confirmation card goes to a person — in the panel or in
Telegram — and no MCP client can press it. A test enforces this.

## Guard your existing automations

Kepil has a small JSON API, so an n8n workflow, a Make scenario or your own
script can ask permission before acting:

```bash
curl -X POST http://localhost:7317/api/check   -H "Authorization: Bearer $KEPIL_API_TOKEN"   -H "Content-Type: application/json"   -d '{"order_id":"ord-0042","action":"send:message","system":"whatsapp.local"}'
```

```json
{ "decision": "await_human", "allowed": false, "needs_human": true,
  "reason": "необратимое действие: требуется подтверждение человека" }
```

The answer is recorded in the journal, so later you can show on what grounds the
automation did — or did not do — something. For n8n there is a ready node:
[n8n-nodes-kepil](https://github.com/oleg-vdv/n8n-nodes-kepil).

**The API stays off until you set a token** (panel → Settings, or
`KEPIL_API_TOKEN`). A panel bound to localhost is protected by the binding; a
programmatic interface is not, so it is disabled by default.

## An agent here is never fully autonomous

`AgentPassport` refuses to be constructed with the autonomy class where a human
can no longer cancel a decision. That is a deliberate architectural limit rather
than a missing feature — see
[ADR-0002](docs/decisions/ADR-0002-medium-autonomy.md). The gate enforces the
same rule regardless of what a profession definition claims.

## Professions: behaviour as data, not code

An agent's job is a JSON description: ordered steps, boundaries, limits,
irreversible action patterns, rollback rules. Adding a new kind of work means
adding a file — or filling in a form in the panel. The dangerous parts stay in
code and under test.

Five ship with the project: inbound leads, process automation, bookkeeping
documents, AI-adoption audit, public-procurement packages.

## Undo that stops honestly

An order's journal is a sequence of actions and every profession declares the
compensating action for each, so the panel can walk it backwards: pick a window,
and the pass runs from the last action towards earlier ones, stopping at the
first one that cannot be undone. What will happen is shown **before** the button
is pressed, naming the step where the pass will stop — an undo promise that
quietly fails is worse than no undo at all. The result is recorded as an
operator's decision, which is why neither the MCP server nor the JSON API can
roll anything back: an agent undoing its own actions would be signing in
somebody else's name.

## The panel

`python -m kepil.admin` opens an operator console: orders, professions, agent
passports, a meter (actions, tokens, cost, human time replaced), the compliance
generator, the journal with chain verification and anchoring, and settings.

State is plain JSON files under `KEPIL_DATA` (default `./data`). No database:
you can open them, read them, and attach them to a dispute.

### The confirmation round trip is what witnesses the log

A hash chain proves the surviving records agree with each other. It says nothing
about what was removed: cut the journal at record 3, rewrite everything after it
with correct `prev_hash` values, and verification prints Integrity confirmed over
a shorter history that is perfectly consistent with itself.

The fix was already in the design without being used. The confirmation card
leaves the writer process and goes to a person, in the panel or in Telegram, and
that round trip is the one artifact produced outside the writer. So the card now
carries the current chain head, the decision that comes back quotes the head it
saw, and the journal records it.

A rewritten prefix now has to contradict a message sitting somewhere the writer
cannot reach. Verification stops being a self-consistency check and becomes a
second party's statement about what the log looked like at a given moment.

```
chain against itself:  Integrity confirmed
witnessed head:        confirmation at record 0 refers to root sha256:a3d124b9…,
                       which is no longer in the chain: the history was cut or
                       rewritten (3 such confirmations)
```

Records written after the last witnessed head stay unprotected. That is where
the guarantee stops, and it says so.

This came from a reader, [ANP2 Network](https://dev.to/olegvdv/i-tried-to-forge-my-own-ai-agents-audit-log-3chh),
who described both the attack and the fix in one comment.

## Survey: what the installation proves, and what a person must answer

A compliance survey is a list of questions bound to legal norms. Some of the
answers are already in the installation — risk and autonomy class in the
passport, documentation completeness in the pack, confirmations and stops in the
journal. The rest a person has to answer: the provenance of training data, the
feature list of a model, insurance contracts.

The panel runs a checklist and splits every item into three: closed by evidence
from the installation, a gap, or *needs a human*. On a real installation about a
fifth closes automatically. If it closed much more than that, the checklist
would be incomplete.

Two properties are worth stating. A resolver returns a fact — "no high autonomy
declared", "zero stops in the journal" — never a verdict of compliance; the
conclusion and the signature stay with a person. And a checklist file references
the *name* of a resolver declared in code and contains nothing executable,
because otherwise a JSON file from elsewhere would be a way to run code on the
machine that keeps the journal.

The integrity resolver reports the system's own weakness: if the chain root has
never been fixed, or is fixed unsigned next to the journal, there is no outside
witness and the whole history could be rewritten.

```
8.2  needs a human   anchors exist, but 1 of 1 is unsigned and stored next to
                     the journal — there is no outside witness
```

## Compliance packs

Documentation requirements differ by country and change faster than code, so the
texts live outside the engine. The neutral pack shipped here follows
international practice (ISO/IEC 42001, record-keeping in the spirit of the EU AI
Act). Jurisdiction packs — for example Kazakhstan's AI Law No. 230-VIII with
order No. 95/НҚ — are dropped into `$KEPIL_DATA/packs` as files.

## Design rules

- **Zero dependencies.** The core runs on the Python 3.11+ standard library, and
  CI fails the build if a third-party import appears. That keeps Kepil
  installable inside an air-gapped perimeter, and keeps the supply-chain attack
  surface of a tool that sees every action at zero.
- **Values never enter the journal** — only types, counts and hashes.
- **The verifier is a separate implementation in another language.** Proof that
  only its own author can check is not proof.

## Related projects

| Project | Role |
|---|---|
| [agent-trace](https://github.com/oleg-vdv/agent-trace) | Independent journal verification and evidence packs (MIT) |
| [AI-Gateway](https://github.com/oleg-vdv/AI-Gateway) | PII and secret masking between your apps and external models |
| [AutoGov](https://github.com/oleg-vdv/AutoGov) | Discovery of shadow automations and the credentials they can reach |

## Status

Alpha, 115 tests. Interfaces may still change. Nothing here is a legal opinion:
before relying on generated documents, have them reviewed by a lawyer in your
jurisdiction.

## License

AGPL-3.0-or-later. Running a network service built on Kepil obliges you to
release your own source under the same terms — or to take a commercial licence.
See [NOTICE.md](NOTICE.md).
