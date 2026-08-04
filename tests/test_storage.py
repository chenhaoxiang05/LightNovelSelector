from lightnovel_selector.models import BookIdentity, ResolveResult
from lightnovel_selector.storage import resolve_result_to_dict


def test_resolve_result_to_dict():
    identity = BookIdentity(
        title="My Title",
        series_name="My Series",
        authors=("Author 1", "Author 2"),
        volume_number=1,
        language="zh",
        tags=("Tag1", "Tag2")
    )

    result = ResolveResult(
        source="Test Source",
        confidence=0.95,
        local_guess="Local Guess",
        metadata_title="My Title",
        metadata_summary="Meta Summary",
        metadata_cover_url="http://example.com/cover.jpg",
        metadata_url="http://example.com",
        identity=identity
    )

    serialized = resolve_result_to_dict(result)

    assert serialized == {
        "series_name": "My Series",
        "identity": {
            "title": "My Title",
            "series_name": "My Series",
            "authors": ["Author 1", "Author 2"],
            "volume_number": 1,
            "language": "zh",
            "tags": ["Tag1", "Tag2"],
        },
        "source": "Test Source",
        "confidence": 0.95,
        "local_guess": "Local Guess",
        "metadata_title": "My Title",
        "metadata_summary": "Meta Summary",
        "metadata_cover_url": "http://example.com/cover.jpg",
        "metadata_url": "http://example.com",
    }

def test_resolve_result_to_dict_null_metadata():
    identity = BookIdentity(
        title="My Title",
        series_name="My Series"
    )

    result = ResolveResult(
        source="Test Source",
        confidence=0.95,
        local_guess="Local Guess",
        identity=identity
    )

    serialized = resolve_result_to_dict(result)

    assert serialized == {
        "series_name": "My Series",
        "identity": {
            "title": "My Title",
            "series_name": "My Series",
            "authors": [],
            "volume_number": None,
            "language": None,
            "tags": [],
        },
        "source": "Test Source",
        "confidence": 0.95,
        "local_guess": "Local Guess",
        "metadata_title": "My Title",
        "metadata_summary": None,
        "metadata_cover_url": None,
        "metadata_url": None,
    }
