# Workflow

## Input Completeness Check

Required fields and defaults:

| Field | Purpose | Missing behavior |
|---|---|---|
| School/OPAC | Select catalog | Default to Chengdu University OPAC |
| Major | Keyword and ranking weights | Ask if also missing goal |
| Stage/year | Reading difficulty | Assume lower/middle undergraduate |
| Goal | Learning route | Ask if also missing major |
| Purpose | Course/exam/research/career | Assume course learning + introductory exploration |
| Network status | Decide live OPAC access | Try access first; ask on failure |
| External books accepted | Decide external supplement | Assume a small supplement is acceptable |
| Output depth | Decide report length | Default `normal` |

If the user only says "帮我找书" or provides neither major nor goal, ask at most:

1. 你是什么专业和年级？
2. 你找书主要为了课程、考研、科研入门还是职业技能？
3. 你现在能访问成都大学图书馆 OPAC 吗？在校园网或 VPN 内吗？

## Execution Flow

1. Record profile, defaults, and output depth.
2. Check OPAC accessibility. Prefer campus network; VPN may work but is not assumed.
3. Check cache validity before live collection.
4. Build a learning route from `route-templates.md`.
5. Expand keywords from `keyword-expansion.md`.
6. Search OPAC by publication year descending.
7. Open details for candidate records and verify title, author, publisher, year, subject, abstract, call number, holdings, barcodes, and status.
8. Resolve location from barcode navigation when possible.
9. Merge editions and remove exam guides, exercises, low-relevance items, and unsuitable theses.
10. Rank library holdings and learning-value books separately.
11. Map books to courses, abilities, and career directions.
12. Analyze collection gaps and external supplements.
13. Run quality control.
14. Produce the report using `report-template.md`.

## Cache Strategy

Use separate cache namespaces to reduce repeated OPAC access without letting
slow-changing metadata extend the lifetime of volatile borrow status.

| Data | TTL |
|---|---:|
| Keyword search results | 30 days |
| Bibliographic metadata | 30 days |
| Borrow/holding status | 3 days |
| Shelf navigation/location | 30 days |

Flow:

```text
cache
↓
per-namespace TTL and JSON integrity check
↓
incremental live verification
↓
atomic cache update + provenance timestamp
```

Legacy metadata caches may contain embedded holdings. Migrate them only when the
original cache timestamp is no more than 3 days old, and preserve that timestamp.
Write and read-verify the independent holdings cache before clearing embedded
holdings from metadata. If that write fails, preserve the old file but do not
expose its status as current. Ignore older embedded status. Corrupt or
incompatible cache files are safe misses.

Use these exact labels:

| Evidence | Label |
|---|---|
| Cached search | `[检索结果来自缓存]` |
| Cached bibliographic metadata | `[书目来自缓存]` |
| Cached holdings/status | `[馆藏状态来自缓存]` and `[馆藏状态未实时核验]` |
| Cached shelf navigation | `[架位信息来自缓存]` |
| Holdings parsed from a detail response in this run | `[馆藏状态已实时核验]` |
| Missing or non-live holdings verification | `[馆藏状态未实时核验]` |
| Any failed collection step or record-limit truncation | `[部分结果不完整]` |

Every holdings row must include its status source and `status_verified_at`.
“Realtime” means the current collection run successfully requested and parsed
the OPAC detail page. A cache hit is never realtime, even if within 3 days and
even when no request failed.

## Polite Request Policy

- Wait at least 0.8 seconds between OPAC requests by default.
- Retry only HTTP 429/502/503/504 and temporary network failures.
- Make at most 2 retries by default, with 1-second then 2-second exponential
  backoff; respect a longer `Retry-After`.
- Process at most 50 detail records and issue at most 30 live shelf-navigation
  requests per run by default. Limit each keyword search to at most 100 records.
- Allow conservative overrides through request JSON or `--delay`,
  `--max-retries`, `--max-records`, and `--max-location-requests`.
- Never bypass authentication, CAPTCHA, VPN, or access controls.

Write retries, final request failures, truncation, limits, cache write errors,
and per-source counts to `source_log`. A cache write failure must not discard
live evidence or erase the old cache. Tests must use fixtures or mocks rather
than real OPAC traffic.

## Failure Handling

If automation fails:

1. State the failed step: page unreachable, empty search, detail-page failure, holding-status failure, campus/VPN restriction, login restriction, or anti-automation.
2. Preserve successful records and any valid per-namespace cache; never substitute expired holdings status.
3. Record the failure in `source_log` and mark the result `[部分结果不完整]`.
4. Record visible page state or screenshot when available.
5. Provide manual keywords and filters.
6. Ask for search result screenshots, detail page screenshots, or copied OPAC text.
7. Continue in manual-assisted mode and mark status from cache or missing status as `[馆藏状态未实时核验]`.

## Quality Control

Before finalizing, verify:

- Every library Top10 item has a call number and holding location.
- No external book is listed as a library Top10 item.
- Library facts, external data, and judgment are clearly separated.
- Different editions of the same textbook have been merged/compared.
- Exercises, exam guides, and low-relevance books have been removed or marked.
- External books are no more than 8.
- The report includes "明天去图书馆该怎么借".
- Every status has a source and verification timestamp or an explicit missing timestamp.
- Cached status is marked `[馆藏状态来自缓存]` and `[馆藏状态未实时核验]`.
- Failed live OPAC verification and partial results are clearly marked.
- Collector output is used as evidence, not mistaken for the Agent's final academic recommendation.
