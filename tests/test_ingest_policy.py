import pytest

from defend_data.ingest_policy import AIIngestExcluded, assert_ai_ingest_allowed


def test_superpowers_docs_are_excluded():
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(filename="docs/superpowers/specs/design.md")


def test_marker_is_excluded_even_after_rename():
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(
            filename="notes.md", content_prefix="<!-- DEFEND-AI-INGEST: EXCLUDE -->"
        )


@pytest.mark.parametrize(
    "filename",
    ["./docs/superpowers/spec.md", "x/../docs/superpowers/spec.md"],
)
def test_superpowers_docs_are_excluded_after_path_canonicalization(filename):
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(filename=filename)
