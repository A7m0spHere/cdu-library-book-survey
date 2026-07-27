# Hallucination Prevention

Never fabricate:

- call numbers
- holding locations
- holding counts
- barcodes
- borrow status
- shelf navigation
- publisher/year
- external book version data

Keep these categories separate:

```text
馆藏事实 != 外部资料 != 人工判断
```

## Required Tags

| Situation | Tag |
|---|---|
| OPAC not verified | `[未核验]` |
| Search cache used | `[检索结果来自缓存]` |
| Bibliographic cache used | `[书目来自缓存]` |
| Holdings/status cache used | `[馆藏状态来自缓存]` and `[馆藏状态未实时核验]` |
| Shelf/navigation cache used | `[架位信息来自缓存]` |
| Status parsed from detail response during this run | `[馆藏状态已实时核验]` |
| External source used | `[外部资料]` |
| Model/human judgment | `[人工判断]` |
| Live status unknown | `[馆藏状态未实时核验]` |
| A collection step failed or record-limit truncation occurred | `[部分结果不完整]` |

If a fact cannot be verified, omit it or mark it. Do not fill blanks from memory.

Never infer current availability from publication metadata, an old screenshot,
or a cached status. A status is realtime only when the current collector run
successfully requests and parses the OPAC detail page. Cached status must retain
its original verification time and cannot be described as “current”, “realtime”,
or “just verified”.

When OPAC access fails, keep independently valid cached bibliographic or shelf
evidence, omit expired holdings status, record the failed step in `source_log`,
and switch to manual-assisted evidence if needed. The collector supplies
evidence; the Agent alone applies ranking, learning-route, and academic judgment
rules.
