"""layout_qa caption regex: 그림/표 plus 코드/Code/알고리즘/Algorithm forms.

No PDF fixtures — CAPTION_RE / OBJECT_CAPTION_RE are pure prefix checks.
`python -m pytest engine/tests -k "layout_qa or caption" -q`.
"""
import os
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import layout_qa  # noqa: E402

# Accepted: optional bracket + number, matching 그림/Fig. One rejected form.
_CAPTION_ACCEPTED = (
    "[코드 1 - 사건 사이의 지수감쇠와 사건 직후 기억 갱신]",
    "코드 1. 재귀 갱신",
    "[Code 1]",
    "Code 2",
    "[알고리즘 1]",
    "알고리즘 2. 동적계획",
    "[Algorithm 1]",
    "Algorithm 3",
    "[그림 1] 제동 시간",
    "그림 2. 결과",
    "Fig 1",
)
_OBJECT_ACCEPTED = _CAPTION_ACCEPTED + ("표 1. 탐색적 5개 대여소의 특성",)
_REJECTED = "[식 1 - 조건부 강도의 정의]"


def test_caption_re_accepts_code_and_algorithm_forms():
    for text in _CAPTION_ACCEPTED:
        assert layout_qa.CAPTION_RE.match(text), text


def test_object_caption_re_accepts_code_and_algorithm_forms():
    for text in _OBJECT_ACCEPTED:
        assert layout_qa.OBJECT_CAPTION_RE.match(text), text


def test_caption_re_rejects_equation_caption():
    assert layout_qa.CAPTION_RE.match(_REJECTED) is None


def test_object_caption_re_rejects_equation_caption():
    assert layout_qa.OBJECT_CAPTION_RE.match(_REJECTED) is None
