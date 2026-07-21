# Social Reporter Quality Rubric

This agent runs in `message` mode, so this rubric is not sent to an
automatic grader — it documents the bar a human should check a report
against. A complete report satisfies all of the following:

1. **Data source** — post data comes from an actual `read_posts` tool call
   in this reply, not from memory, a prior report, or an assumption about
   what the fixture contains.
2. **Metric** — engagement rate is defined and used exclusively as
   `(likes + comments + reposts) / impressions`. Raw engagement count is
   never used to rank posts.
3. **Per-platform, never pooled** — X and LinkedIn posts are ranked
   separately. No combined/pooled ranking appears anywhere in the reply.
4. **Top posts with arithmetic** — each platform section lists its top posts
   by rate (up to 3, fewer if the platform has fewer posts in the window),
   each showing `(l+c+r)/impressions = rate` explicitly, not just the final
   percentage.
5. **Weakest post per platform** — the single lowest-rate post on each
   platform is named.
6. **Exactly one recommendation** — the reply contains one, and only one,
   content recommendation. It is backed by: (a) categories derived from
   reading the actual post text, (b) at least 2 posts per compared category,
   (c) an explicit ratio (best-category average ÷ rest-of-platform average),
   and (d) an explicit statement of which platform the pattern applies to.
   No generic advice ("post more often," "try video") appears anywhere.
7. **Queued posts are real tool calls** — both drafted posts are queued via
   an actual `queue_post` tool call each (visible in the reply's tool-call
   trace), and the reply cites the tool's own return value (the appended
   entry: id/status/queued_at) as confirmation — not just a claim that
   queuing happened.
8. **Precision** — engagement rates are reported to 3 decimal places
   everywhere they appear.
9. **No overclaiming** — the reply never implies a real X/LinkedIn account
   was read or posted to. Both `read_posts` and `queue_post` are treated as,
   and described as, mock/prototype tools.
