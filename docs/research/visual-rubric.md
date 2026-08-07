# Visual rubric — moved

The visual rubric now lives at **`skill/references/visual-rubric.md`**.

It is part of the shipped skill surface, not a research note: an agent has to
read it to close the vision half of `pipeline/scripts/visual_verify.py`, so it
travels with the skill into every install and every bundle. Shipping it from
`docs/research/` meant a buyer received the mandatory half of the verify loop
with no class definitions at all (v0.17 clean-room finding, trouble-table
T29).

This file is a pointer, not a copy — there is exactly one rubric, and
`tests/test_package_module.py::TestRubricHasOneHome` fails if this stub ever
grows back into a second one.
