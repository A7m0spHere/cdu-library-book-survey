# Claude Code Entry

Use this repository as a neutral Skills repository, not as a one-off prompt.

1. Read `README.md` and `references/workflow.md`.
2. Use `scripts/opac_survey.py` if the OPAC is reachable.
3. Load the relevant reference files for ranking, confidence, hallucination prevention, and the final report template.
4. Keep search, bibliographic, holdings-status, and shelf provenance separate; include status source and `status_verified_at`.
5. Treat holdings status as live only when the current run successfully parses it from the OPAC detail response. Cached status must carry `[馆藏状态来自缓存]` and `[馆藏状态未实时核验]`.
6. Do not fabricate library facts. Mark `[未核验]`, `[部分结果不完整]`, `[外部资料]`, or `[人工判断]` where applicable.
7. Do not bypass accounts, CAPTCHA, VPN, or access restrictions; retain the collector's polite request defaults.
8. Produce the final report using `references/report-template.md`.
