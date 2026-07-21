---
name: weekly-social-report
description: Produce the weekly X/LinkedIn engagement report for this account — per-platform top posts by engagement rate (with arithmetic shown), exactly one data-backed content recommendation, and two drafted posts queued via publish-post.mjs. Use whenever asked for the weekly social report, engagement report, or "what should I post next week."
---

# Weekly social report

Reports on X and LinkedIn post performance for the last 2 weeks and queues
next week's posts. All data in this project is mocked — `scripts/read-posts.mjs`
reads `data/posts.json` instead of calling a real API, and
`scripts/publish-post.mjs` queues to `data/outbox.json` instead of publishing
anywhere. Nothing in this skill ever touches a live account.

## Step 1 — Read the posts

Run, from `managed/social-reporter/`:

```
node scripts/read-posts.mjs --since <14-days-ago, YYYY-MM-DD>
```

Compute `<14-days-ago>` from the current date — don't hardcode a date from a
previous run. `--since` and `--platform` are the only filters the script
supports; if you need one platform, add `--platform x` or `--platform linkedin`
rather than filtering the JSON yourself.

## Step 2 — Compute engagement rate per post

For every post:

```
engagement rate = (likes + comments + reposts) / impressions
```

This is the only metric this report uses to rank posts. Do not rank by raw
`likes + comments + reposts` count — that just rewards whichever post had the
most impressions, and produces a different (wrong) ranking than rate does.
Always compute rate per platform, never pooled across platforms — X and
LinkedIn have structurally different impression/engagement scales, so a
combined ranking is meaningless.

## Step 3 — Rank top posts per platform

Separately for X and for LinkedIn, sort posts by engagement rate descending
and take the top 3 (fewer if the platform has fewer than 3 posts in the
window). For each, show the arithmetic, not just the final percentage, so
the numbers can be checked without re-deriving them:

```
(likes+comments+reposts)/impressions = rate
```

e.g. `(210+41+53)/6,200 = 4.903%`. Also name the single weakest post per
platform (lowest rate) — useful for Step 4 and worth surfacing.

## Step 4 — Derive exactly one data-backed recommendation

Do not produce a list of generic advice ("post more often," "try video," "be
authentic"). Produce exactly one recommendation, and only if the data
actually supports it:

1. Group the posts on one platform into content categories by what they
   actually are (e.g. "no-pitch hot-take/meme," "product ship/feature,"
   "benchmark/numbers," "hiring," "incident/postmortem"). Categories must
   come from reading the post text, not from a fixed taxonomy — invent
   categories that fit what's actually in the dataset.
2. Compute the average engagement rate for each category. Only compare
   categories that have at least 2 posts each — a category of 1 is an
   anecdote, not a pattern, and can't support a ratio claim.
3. Find the largest gap between the best-performing category and "every
   other post on that platform." Express it as a ratio (best avg ÷ rest
   avg), e.g. "1.61:1."
4. State the recommendation as: `<category> outperforms everything else on
   <platform> by <ratio>, so do more <category>.` Name the platform
   explicitly — a pattern found only on X should not be extended to
   LinkedIn (or vice versa) without separate LinkedIn evidence for it.
5. If no category clears roughly 1.3:1 against the rest, say so explicitly
   instead of forcing a recommendation out of noise.

## Step 5 — Draft and queue two posts

Write two new post drafts that fit the winning category from Step 4 — same
register (e.g. no product pitch, relatable pain point), not reuses of the
posts already in `data/posts.json`. Queue both:

```
node scripts/publish-post.mjs --platform <x|linkedin> --text "<draft>"
```

Then read back `data/outbox.json` and confirm both new entries are present
before reporting them as queued — don't claim they landed without checking.

## Output format

Produce exactly these sections, in this order:

```markdown
## Top posts by engagement rate — X

| Rank | Post | Arithmetic | Rate |
| --- | --- | --- | --- |
| 1 | <id> (<short description>, <date>) | (l+c+r)/impressions | **X.XXX%** |
| 2 | ... |
| 3 | ... |

## Top posts by engagement rate — LinkedIn

(same table shape)

Weakest posts: <id> (<platform>, <date>, <rate>) and <id> (<platform>, <date>, <rate>).

## The one recommendation the data supports

<Category> posts on <platform> average **X.XXX%** vs **Y.YYY%** for every
other post on that platform — a **Z.ZZ:1** ratio. <One-sentence
recommendation.> This is <platform>-specific: <note on why it isn't
extended to the other platform, e.g. "the other platform has no posts in
this format to compare">.

## Queued for next week

Two drafts in this register, queued via `scripts/publish-post.mjs` (see
`data/outbox.json`):

1. "<draft 1>"
2. "<draft 2>"
```

Report engagement rates to 3 decimal places throughout, matching the
arithmetic shown in the tables (e.g. `4.903%`, not `4.9%`) so the displayed
rate and the ranking always agree.
