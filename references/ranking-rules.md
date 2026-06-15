# Ranking Rules

## Library Holdings Score

Default weights:

| Dimension | Weight |
|---|---:|
| Match to user goal | 25 |
| Match to current stage | 15 |
| Subject/abstract relevance | 15 |
| Borrow status and location usability | 15 |
| Publication year and edition freshness | 10 |
| Author/publisher/classic status | 10 |
| Importance in the learning route | 10 |

Use the score as guidance, not as a mechanical substitute for academic judgment.

## Library Top10 Hard Rules

- Require call number and holding location.
- Allow missing precise shelf navigation if call number, holding location, and status exist; mark `需到馆内按索书号查找`.
- Exclude external books.
- Exclude pure exercises, exam guides, and low-relevance matches.
- Exclude theses by default unless the user asks for research topics.

## Edition Merge Rules

For same-title/same-textbook families:

- Keep the newest formal textbook edition when it is suitable and borrowable.
- Keep a classic older edition only when it is academically stronger, more available, or fills a rare topic.
- Put older editions in notes, not separate Top10 slots.
- Treat workbook, experiment guide, review guide, and exam guide as auxiliary materials, not main recommendations.
- For translated and original-language versions, choose based on user stage and language ability.

## External Book Rules

- Recommend at most 8 external books.
- Every external book must fill a named gap, upgrade an old holding, or suit the user better than available holdings.
- Mark relationship to holdings: `图书馆未检索到`, `馆藏有相近书但此书更优`, `馆藏有旧版/替代书`, or `馆藏适合入门，此书适合进阶`.
- Verify current bibliographic data from external sources before presenting as fact.

