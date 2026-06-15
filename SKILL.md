---
name: cdu-library-book-survey
description: Agent-neutral Chengdu University library survey workflow. Use when a user wants to research CDU OPAC holdings, recommend books by major/course/exam/research/career goal, compare library holdings with better external books, get call numbers, holding locations, borrow status, barcodes, shelf navigation, produce actionable borrowing lists, or map books to courses, abilities, and career directions.
---

# CDU Library Book Survey Skill

Use this reusable skill as a learning-planning and library-holdings research workflow for Chengdu University students. It must help the user decide which books are worth borrowing, whether they are currently borrowable, where to find them, what collection gaps remain, and whether external books should supplement the library.

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
- Do not present unverified data as library facts.
- Do not mix external books into the "library holdings Top10".
- Do not recommend from title alone; verify details, abstracts, subjects, holdings, or external publication data whenever possible.

## Required Output Rules

- Separate "馆藏推荐 Top10" from "学习价值 Top10".
- Every library Top10 item must include at least title, call number, holding location, borrow status, and evidence source.
- If precise shelf navigation is unavailable but call number and holding location are known, state: `需到馆内按索书号查找`.
- External books may be recommended even when the library has related holdings, but list at most 8 and explain the specific collection gap they fill.
- Every recommendation reason must state what problem the book solves, the suitable stage, and why it is recommended.
- Before finalizing, perform the quality checklist in [references/workflow.md](references/workflow.md).

## Script Quick Start

Create an input JSON:

```json
{
  "profile": {
    "school": "成都大学",
    "major": "药学",
    "stage": "大二",
    "goal": "AI制药",
    "purpose": "课程学习+科研入门",
    "network": "校园网或VPN",
    "output_depth": "normal"
  },
  "keywords": ["药物化学", "药理学", "药物设计学", "计算机辅助药物设计", "化学信息学"],
  "max_results_per_keyword": 50
}
```

Run:

```bash
python3 scripts/opac_survey.py --input request.json --output survey.json --format json
```

If the script uses cache or cannot verify live OPAC data, mark affected output with `[缓存数据]` and/or `[未实时核验]`.
