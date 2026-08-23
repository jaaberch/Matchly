"""ffprobe output parsing.

Tested against recorded payloads rather than live ffmpeg, so the awkward cases —
fractional frame rates, rotated phone video, a stream with no audio — are covered
whether or not ffmpeg is installed.
"""

from __future__ import annotations

import pytest

from video_worker.ffmpeg import MediaInfo, parse_probe


def _payload(*, streams: list[dict], fmt: dict | None = None) -> dict:
    return {"streams": streams, "format": {"duration": "3600.5"} if fmt is None else fmt}


VIDEO = {
    "codec_type": "video",
    "codec_name": "h264",
    "width": 3840,
    "height": 2160,
    "avg_frame_rate": "30000/1001",
    "r_frame_rate": "30000/1001",
}
AUDIO = {"codec_type": "audio", "codec_name": "aac"}


def test_a_typical_4k_recording() -> None:
    info = parse_probe(_payload(streams=[VIDEO, AUDIO]))

    assert info.duration == 3600.5
    assert (info.width, info.height) == (3840, 2160)
    assert info.fps == pytest.approx(29.97, abs=0.01)
    assert info.has_audio is True
    assert info.video_codec == "h264"


def test_fractional_frame_rates_become_floats() -> None:
    # ffprobe reports 30000/1001, never 29.97.
    assert parse_probe(_payload(streams=[{**VIDEO, "avg_frame_rate": "25/1"}])).fps == 25.0
    assert parse_probe(_payload(streams=[{**VIDEO, "avg_frame_rate": "24000/1001"}])).fps == (
        pytest.approx(23.976, abs=0.001)
    )


def test_a_zero_denominator_does_not_divide_by_zero() -> None:
    # Still images and some broken files report 0/0.
    info = parse_probe(
        _payload(streams=[{**VIDEO, "avg_frame_rate": "0/0", "r_frame_rate": "0/0"}])
    )
    assert info.fps is None


def test_it_falls_back_to_r_frame_rate() -> None:
    info = parse_probe(
        _payload(streams=[{**VIDEO, "avg_frame_rate": None, "r_frame_rate": "50/1"}])
    )
    assert info.fps == 50.0


def test_a_silent_recording() -> None:
    # Plenty of pitch cameras have no microphone; the audio signal is then simply
    # unavailable to the scorer.
    assert parse_probe(_payload(streams=[VIDEO])).has_audio is False


def test_no_video_stream() -> None:
    info = parse_probe(_payload(streams=[AUDIO]))
    assert info.width is None and info.height is None
    assert info.has_audio is True


@pytest.mark.parametrize("rotation", [90, 270, -90])
def test_rotated_video_reports_what_a_viewer_sees(rotation: int) -> None:
    payload = _payload(
        streams=[
            {**VIDEO, "width": 1920, "height": 1080, "side_data_list": [{"rotation": rotation}]}
        ]
    )
    info = parse_probe(payload)
    assert (info.width, info.height) == (1080, 1920)


def test_upright_video_is_left_alone() -> None:
    payload = _payload(streams=[{**VIDEO, "side_data_list": [{"rotation": 0}]}])
    assert parse_probe(payload).width == 3840


def test_legacy_rotate_tag_is_honoured() -> None:
    payload = _payload(streams=[{**VIDEO, "width": 1920, "height": 1080, "tags": {"rotate": "90"}}])
    assert parse_probe(payload).width == 1080


def test_duration_falls_back_to_the_stream() -> None:
    info = parse_probe({"streams": [{**VIDEO, "duration": "120.25"}], "format": {}})
    assert info.duration == 120.25


@pytest.mark.parametrize("duration", [None, "", "N/A", "not-a-number"])
def test_unusable_durations_become_none(duration) -> None:
    fmt = {} if duration is None else {"duration": duration}
    assert parse_probe(_payload(streams=[VIDEO], fmt=fmt)).duration is None


def test_bit_rate_is_optional() -> None:
    assert parse_probe(_payload(streams=[VIDEO], fmt={"bit_rate": "8000000"})).bit_rate == 8000000
    assert parse_probe(_payload(streams=[VIDEO], fmt={"bit_rate": "N/A"})).bit_rate is None


def test_as_dict_is_json_safe() -> None:
    import json

    info = parse_probe(_payload(streams=[VIDEO, AUDIO]))
    assert isinstance(info, MediaInfo)
    json.dumps(info.as_dict())  # must not raise: this goes into a JSONB column
