# Poster content file

`poster_build.py` fills a `.pptx` poster form from this markdown. The form
is copied, never modified. Body text is written at `--min-pt` (default 24)
in 맑은 고딕; overflow is a hard failure (fonts are never shrunk to fit).

```
# TITLE: Poster title
# AUTHORS: Name, Affiliation
# HEADER_SHAPE: optional-header-shape-name

box_map:
{"intro": ["ShapeIntro", "LabelIntro"], "method": ["ShapeMethod", null]}

## BOX: intro
Paragraph one.

[[FIG file="plot.png" caption="Caption under the figure"]]

## BOX: method
Body of the second box.
```

`box_map` is a JSON object: each box key maps to
`[content_shape_name, label_shape_or_null]`. A non-null label's bottom edge
pushes the text start down. Put the map in this header, or pass
`--box-map boxes.json` (or an inline JSON object); `--box-map` wins. If
neither is given, a six-box legacy fallback (`연구동기`, `이론적배경`,
`연구과정A`, `연구과정B`, `결론`, `참고문헌`) keeps older content working.

`--figures` names files in `[[FIG file=...]]`. `--form` is the template;
`--out` is the filled copy. `poster_verify.py` checks form mtime, leftover
guide strings, the 24 pt floor, and optional `--require-text` /
`--min-pictures` / `--numbers`.
