---
name: cdu-library-book-survey
description: Agent-neutral Chengdu University library recommendation skill. Use when a user wants to research CDU OPAC holdings, recommend books by major/course/exam/research/career goal, compare library holdings with better external books, get call numbers, holding locations, borrow status, barcodes, shelf navigation, produce actionable borrowing lists, or map books to courses, abilities, and career directions.
---

# CDU Library Book Survey Skills

Use this reusable skills repository as a learning-planning and library-holdings research skill for Chengdu University students. It must help the user decide which books are worth borrowing, whether they are currently borrowable, where to find them, what collection gaps remain, and whether external books should supplement the library.

## First Steps

1. Read [references/workflow.md](references/workflow.md) for the complete execution workflow.
2. If OPAC collection is possible, use [scripts/opac_survey.py](scripts/opac_survey.py) to collect search results, detail pages, holdings, barcodes, and shelf navigation data.
3. Load only the reference files needed for the task:
   - keywords: [references/keyword-expansion.md](references/keyword-expansion.md)
   - scoring and version merge: [references/ranking-rules.md](references/ranking-rules.md)
   - confidence: [references/confidence-rules.md](references/confidence-rules.md)
   - reading cost: [references/reading-cost-rules.md](references/reading-cost-rules.md)
   - route/capability mapping: [references/route-templates.md](references/route-templates.md), [references/capability-mapping.md](references/capability-mapping.md)
   - collection gaps: [references/gap-analysis.md](references/gap-analysis.md)
   - hallucination prevention: [references/hallucination-prevention.md](references/hallucination-prevention.md)
   - recommendation wording: [references/recommendation-rules.md](references/recommendation-rules.md)
   - final report: [references/report-template.md](references/report-template.md)

## Access Prerequisites

CDU OPAC may only be reachable from the Chengdu University campus network or through the university VPN. Do not assume VPN works unless the user confirms it. First try the OPAC URL:

`http://libopac.cdu.edu.cn/opac/search_adv.php#/index`

If inaccessible, ask the user to connect to campus network/VPN or provide screenshots/copied results for manual-assisted analysis.

## Do Not

- Do not log into the user's library account.
- Do not query personal borrowing records.
- Do not reserve, renew, or recommend-purchase books unless the user explicitly asks and the system supports it.
- Do not high-frequency crawl OPAC.
- Do not bypass login, CAPTCHA, VPN, or access restrictions.
- Do not present unverified data as library facts.
- Do not mix external books into the "library holdings Top10".
- Do not recommend from title alone; verify details, abstracts, subjects, holdings, or external publication data whenever possible.

## Required Output Rules

- Separate "馆藏推荐 Top10" from "学习价值 Top10".
- Every library Top10 item must include at least title, call number, holding location, borrow status, status source, status verification time, and evidence source.
- If precise shelf navigation is unavailable but call number and holding location are known, state: `需到馆内按索书号查找`.
- External books may be recommended even when the library has related holdings, but list at most 8 and explain the specific collection gap they fill.
- Every recommendation reason must state what problem the book solves, the suitable stage, and why it is recommended.
- Treat borrow status as live only when this collection run successfully requested and parsed the OPAC detail page. Cached status is never described as live, even if it is within its 3-day TTL.
- Before finalizing, perform the quality checklist in [references/workflow.md](references/workflow.md).

## Script Quick Start

Create an input JSON:

```json
{
  "profile": {
    "school": "成都大学",
    "major": "专业名称",
    "stage": "年级或学习阶段",
    "goal": "学习或研究目标",
    "purpose": "课程学习",
    "network": "未知",
    "output_depth": "normal"
  },
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "max_results_per_keyword": 30,
  "max_records": 50,
  "max_location_requests": 30,
  "refresh": false,
  "request_delay_seconds": 0.8,
  "max_retries": 2
}
```

Run:

```bash
python3 scripts/opac_survey.py --input request.json --output survey.json --format json
```

The collector keeps separate caches for search results (30 days), bibliographic
metadata (30 days), holdings/status (3 days), and shelf navigation (30 days).
Its default request interval is 0.8 seconds, with at most two retries for
temporary failures, 50 detail records, and 30 live shelf requests per run.

Use the exact provenance labels returned by the script. Cached holdings must
carry `[馆藏状态来自缓存]` and `[馆藏状态未实时核验]` plus their original
`status_verified_at`; only a detail response parsed during the current run may
carry `[馆藏状态已实时核验]`. Record incomplete requests as
`[部分结果不完整]` and retain the `source_log`.

The JSON contracts and examples are
[schemas/request.schema.json](schemas/request.schema.json),
[schemas/survey.schema.json](schemas/survey.schema.json), and [examples/](examples/).
They describe collected evidence only. Recommendation rankings, learning routes,
and final academic judgments remain the Agent's responsibility.
