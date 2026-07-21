# Weekly social report — week ending 2026-07-21

Source: `scripts/read-posts.mjs --since 2026-07-07` (12 posts, 8 X / 4 LinkedIn, mock data).

## Engagement summary

| Platform | Posts | Impressions | Likes | Comments | Reposts | Eng. rate* |
| --- | --- | --- | --- | --- | --- | --- |
| X | 8 | 30,500 | 714 | 154 | 166 | 3.4% |
| LinkedIn | 4 | 11,000 | 288 | 74 | 39 | 3.6% |
| **Total** | **12** | **41,500** | **1,002** | **228** | **205** | **3.5%** |

\*Engagement rate = (likes + comments + reposts) / impressions.

Two outliers pulled the average up: the flaky-tests meme (p10) and the "AI-powered devtool" hot take (p4). Excluding those two, the remaining 10 posts average ~2.6% — a more realistic baseline for planning next week.

## Top posts by engagement rate — X

Rate = (likes + comments + reposts) / impressions.

| Rank | Post | Arithmetic | Rate |
| --- | --- | --- | --- |
| 1 | p10 (flaky test meme, 07-17) | (210+41+53)/6,200 | **4.903%** |
| 2 | p4 (AI-pitch hot take, 07-10) | (142+38+27)/5,400 | **3.833%** |
| 3 | p1 (benchmark thread, 07-07) | (96+19+31)/4,100 | **3.561%** |

## Top posts by engagement rate — LinkedIn

| Rank | Post | Arithmetic | Rate |
| --- | --- | --- | --- |
| 1 | p2 (DevRel hire, 07-08) | (74+21+9)/2,600 | **4.000%** |
| 2 | p11 (backend hiring, 07-18) | (58+24+11)/2,400 | **3.875%** |
| 3 | p5 (12k installs milestone, 07-11) | (89+16+12)/3,100 | **3.774%** |

Weakest posts (lowest rate per platform): p7 (X, thread follow-up, 07-13, 2.048% rate) and p8 (LinkedIn, technical deep-dive, 07-15, 3.000% rate).

## The one recommendation the data supports

On X, no-pitch hot-take/meme posts (p4, p10) average **4.368%** engagement rate. The other 6 X posts — benchmarks, ship announcements, customer quotes, changelog, incident writeup (p1, p3, p6, p7, p9, p12) — average **2.720%**. That's a **1.61:1** ratio.

**Do more no-pitch hot-take/meme posts on X.** This is X-specific: LinkedIn has no posts in this format in the dataset, so the ratio isn't extended there.

## Queued for next week

Two drafts in this register, queued via `scripts/publish-post.mjs` (see `data/outbox.json`):

1. "hot take: 'it's just a config change' has caused more outages this year than every actual code change combined. we should treat YAML like it's production code, because it is"
2. "signs your CI pipeline needs an intervention: 1) the retry count is higher than the test count 2) someone wrote a script called fix_ci_pls.sh 3) the flaky test has its own Slack channel 4) you've stopped reading the red X and just rerun"

---
*Generated from mock data (`data/posts.json`) — no real X/LinkedIn accounts are connected yet. `scripts/publish-post.mjs` is a mock stand-in that queues to `data/outbox.json`, not a live publish API.*
