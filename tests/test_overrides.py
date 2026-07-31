from ymd.overrides import apply_metadata_overrides, load_overrides, upsert_override


def test_specific_manual_override_wins_and_records_source(tmp_path):
    path = tmp_path / "overrides.json"
    upsert_override(
        path,
        {
            "match": {"artist": "Triple Seven", "album": "Rompiendo Los Limites"},
            "values": {"genre": "Hip Hop", "publisher": "Sello verificado"},
        },
    )
    result = apply_metadata_overrides(
        {"artist": "Triple Seven", "album": "Rompiendo Los Límites", "genre": ""},
        load_overrides(path),
    )
    assert result["genre"] == "Hip Hop"
    assert result["genre_source"] == "user_override"
    assert "manual" in result["metadata_sources_used"]


def test_override_requires_match_and_allowed_value(tmp_path):
    path = tmp_path / "overrides.json"
    try:
        upsert_override(path, {"match": {}, "values": {"genre": "Rock"}})
    except ValueError:
        pass
    else:
        raise AssertionError("An unscoped override must be rejected")
