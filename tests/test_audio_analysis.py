from ymd.audio_analysis import parse_loudnorm_output


def test_parse_loudnorm_output_builds_replaygain_values():
    result = parse_loudnorm_output(
        'noise\n{"input_i":"-14.00","input_tp":"-1.00","target_offset":"0.0"}\n'
    )
    assert result["replaygain_track_gain"] == "-4.00 dB"
    assert result["replaygain_track_peak"] == "0.89125094"
    assert result["loudness_integrated"] == "-14.00 LUFS"


def test_parse_loudnorm_output_ignores_invalid_payload():
    assert parse_loudnorm_output("not json") == {}
