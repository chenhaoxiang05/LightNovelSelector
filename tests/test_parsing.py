import pytest

from lightnovel_selector.parsing import is_noise_tag


@pytest.mark.parametrize(
    "value, position, expected",
    [
        # Empty and whitespace
        ("", "leading", True),
        ("   ", "leading", True),
        # Known noise words
        ("epub", "leading", True),
        ("epub", "trailing", True),
        ("lightnovel", "leading", True),
        # Contains noise words
        ("some epub file", "leading", True),
        ("color illustrations", "leading", True),
        # Volume numbers trailing vs leading
        ("v1", "trailing", True),
        ("v1", "leading", False),
        ("vol 2", "trailing", True),
        ("vol 2", "leading", False),
        ("volume3", "trailing", True),
        ("volume3", "leading", False),
        ("book 4", "trailing", True),
        ("book 4", "leading", False),
        ("12", "trailing", True),
        ("12", "leading", False),
        # Chinese volume markers (always true regardless of position)
        ("第1卷", "leading", True),
        ("第1卷", "trailing", True),
        ("第2册", "leading", True),
        ("第2册", "trailing", True),
        # Not noise
        ("sword art online", "leading", False),
        ("sword art online", "trailing", False),
        ("some random string", "leading", False),
        ("some random string", "trailing", False),
    ],
)
def test_is_noise_tag(value, position, expected):
    assert is_noise_tag(value, position=position) == expected
