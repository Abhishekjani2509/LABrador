# Claude Agent Starter — Audience

Who this repo is written for, what that reader already believes walking in, and
what that implies for how it's put together. Companion to `frame.md`
(problem/outcome).

## The YC batch founder

~200 companies, mostly 2–4 person technical teams, in week one of the batch.
Composite reader:

- **Technical co-founder writing the code themselves.** Reads code before
  prose; will clone the repo before finishing the README. Judges a platform by
  time-to-first-working-thing, not by feature matrices.
- **Deciding the AI platform *this week*, mostly by default.** They've
  experimented with OpenAI, Gemini, and Claude already; whichever gets embedded
  in the MVP now tends to stick. The decision is rarely a bake-off — it's
  whatever removed friction first.
- **Anchored on credit headlines.** Their inbox has a cloud-credit offer from
  every major lab, and Anthropic's isn't the biggest headline number. This repo
  doesn't fight on that field.
- **Time-poor and demo-day-driven.** Weekly YC check-ins ask what shipped.
  Anything that takes more than an evening to evaluate doesn't get evaluated.
  "Shipped in under a week" is the ceiling of their patience, not the target.
- **Marketing-immune, peer-permeable.** They skim vendor email in seconds and
  distrust polish; they act on "another founder got this working" and on
  runnable code. Voice matters: a founder writing to founders, not DevRel copy.

## What they already believe, and the counter

| Belief walking in | Counter this repo carries |
| --- | --- |
| "The biggest credit check makes this a non-decision" | At 2–4-person-team burn, nobody exhausts any of these offers — the binding constraint is shipping speed, not credits. |
| "Claude is the coding model; my *product* runs on someone's API" | The continuum is the pitch: the Claude Code session where your agent first worked *is* the source — `/managed-agent-prototype` gets it working there, `/managed-agent-deploy` compiles that same session into a deployed Managed Agent. Prototype tool and production platform are one system. |
| "My prototype works in a chat session, but productionizing it is a rewrite" | That's the exact dead end the starter removes — the transcript where it finally worked is the spec, not a throwaway. |
| "Managed Agents is a beta; betas cost me integration time" | The starter is the integration: deploy script, session runtime, streaming router, and the two-skill flow that ships your first customer's agent. What's normally week-two glue is cloned in minute one. |
| "Platform choice is an architecture decision I should think hard about" | It's a week you don't have. Every day of the batch counts in customers onboarded, and whatever you engineer against customer one is wrong by customer 10. The starter answers LangChain-vs-LangGraph-vs-SDK, state, and sandbox hosting so the week goes to customers instead. |
| "I still have to build the Slack/frontend layer myself" | The eve router is the last mile — channels and streaming out of the box, compiled agents as its tools. It arrives late in the story on purpose: the platform is the lead, eve is the last mile. |

## What actually moves them

1. A money line that survives a skim: *"the transcript where it finally worked
   is the spec."*
2. Runnable proof over claims — clone, one command, watch a deployed agent
   answer.
3. The move recognizable as their week, not the example recognizable as their
   vertical: one customer met at an event and onboarded the same day. What
   generalizes is forward-deployed engineering per customer — a founder in
   devtools or fintech doesn't need a devtools or fintech demo to see their own
   next customer in it.
4. Speed receipts: concrete "meet them at the event, endpoint that night," ~20
   minutes from working session to deployed agent — not "accelerate your AI
   journey."

## What that implies for the README

It's read *after* cloning, half as reference while running commands. So the
first ~50 lines sell the platform story — opening, why-this-shape, then steps
1→4 — and everything below is copy-paste-runnable, with the architecture
diagram for the co-founder who evaluates before committing.
