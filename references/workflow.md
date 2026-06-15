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

Use cache to reduce repeated OPAC access.

| Data | TTL |
|---|---:|
| Bibliographic metadata | 30 days |
| Shelf navigation/location | 30 days |
| Keyword search results | 30 days |
| Borrow/holding status | 3 days |

Flow:

```text
cache
↓
TTL and required-field check
↓
incremental live verification
↓
update result
```

If live access fails and cache is used, mark affected data with `[缓存数据]` and `[未实时核验]`.

## Failure Handling

If automation fails:

1. State the failed step: page unreachable, empty search, detail-page failure, holding-status failure, campus/VPN restriction, login restriction, or anti-automation.
2. Record visible page state or screenshot when available.
3. Provide manual keywords and filters.
4. Ask for search result screenshots, detail page screenshots, or copied OPAC text.
5. Continue in manual-assisted mode and mark unrealtime data.

## Quality Control

Before finalizing, verify:

- Every library Top10 item has a call number and holding location.
- No external book is listed as a library Top10 item.
- Library facts, external data, and judgment are clearly separated.
- Different editions of the same textbook have been merged/compared.
- Exercises, exam guides, and low-relevance books have been removed or marked.
- External books are no more than 8.
- The report includes "明天去图书馆该怎么借".
- Failed live OPAC verification is clearly marked.

