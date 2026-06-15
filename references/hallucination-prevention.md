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
| Cache used | `[缓存数据]` |
| External source used | `[外部资料]` |
| Model/human judgment | `[人工判断]` |
| Live status unknown | `[未实时核验]` |

If a fact cannot be verified, omit it or mark it. Do not fill blanks from memory.

