# Confidence Rules

Every recommended book needs confidence.

| Level | Meaning |
|---|---|
| A | In this collection run, the OPAC detail page and holdings status were parsed successfully, and location/shelf data is live-verified |
| B | In this collection run, the OPAC detail page and holdings status were parsed successfully, but precise shelf data is cached or missing |
| C | Holdings status is cached/unverified, or holdings/version/location evidence is incomplete |
| D | Based on user goal and partial overview; explicitly mark as judgment |

## Evidence Labels

Allowed evidence labels:

- OPAC检索结果
- OPAC详情页
- 馆藏条码页
- 图书定位页
- 目录/摘要
- 外部出版信息
- 人工判断
- `[检索结果来自缓存]`
- `[书目来自缓存]`
- `[馆藏状态来自缓存]`
- `[架位信息来自缓存]`
- `[馆藏状态已实时核验]`
- `[馆藏状态未实时核验]`
- `[部分结果不完整]`

Every holdings status needs a source (`live`, `cache`, or `unverified`) and a
verification timestamp. Only a status parsed from an OPAC detail response in the
current collection run is `live`. Cached status remains
`[馆藏状态未实时核验]`, regardless of age within the 3-day TTL.

Do not use confidence A when any required status or shelf evidence is cached,
missing, or failed. External publication evidence can support relevance
judgment, but it cannot upgrade OPAC holdings confidence.
