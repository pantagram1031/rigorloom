# Bounded humanization prompt

Use `bundle/humanization_report.json` for stable paragraph ids and
`bundle/ai_tell_review.json` for the approved targets. Read the optional local
writing profile when present.

Rewrite only targeted paragraphs. Make the smallest change that resolves the
cited pattern. Preserve the academic register, student level, factual meaning,
numbers, units, equations, tags, source ids, headings, uncertainty, negation,
and logical direction exactly.

Return only the change schema from
`pipeline/references/humanization_contract.md`. Copy each `before` paragraph
exactly from the report. Do not return a full rewritten document.
