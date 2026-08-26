from app.core.slugs import slugify


def test_basic_slugify():
    assert slugify("The Last Summer") == "the-last-summer"


def test_strips_punctuation():
    assert slugify("Wait, What?! (A Story)") == "wait-what-a-story"


def test_normalizes_accents():
    assert slugify("Café — Été") == "cafe-ete"


def test_collapses_whitespace_and_dashes():
    assert slugify("  too   many   spaces  ") == "too-many-spaces"


def test_empty_input_has_fallback():
    assert slugify("") == "untitled"
    assert slugify("!!!") == "untitled"
