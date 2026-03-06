"""Tests for madam.ffmpeg.combine() — create video from image frames."""

import io

import PIL.Image
import pytest

import madam.core
from madam.core import UnsupportedFormatError


def _make_image_asset(color=(255, 0, 0), size=(64, 48), mime_type='image/jpeg'):
    """Create a solid-color image asset for use as a video frame."""
    img = PIL.Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, 'JPEG')
    buf.seek(0)
    return madam.core.Asset(buf, mime_type=mime_type, width=size[0], height=size[1])


@pytest.fixture(scope='module')
def red_frame():
    return _make_image_asset((200, 50, 50))


@pytest.fixture(scope='module')
def blue_frame():
    return _make_image_asset((50, 50, 200))


class TestCombineVideo:
    def test_combine_video_returns_asset(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        result = combine([red_frame, blue_frame], 'video/mp4', fps=1.0)
        assert isinstance(result, madam.core.Asset)

    def test_combine_video_mime_type(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        result = combine([red_frame, blue_frame], 'video/mp4', fps=1.0)
        # mp4 round-trips as quicktime
        assert result.mime_type in ('video/mp4', 'video/quicktime')

    def test_combine_video_has_duration(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        result = combine([red_frame, blue_frame], 'video/mp4', fps=1.0)
        assert result.duration > 0

    def test_combine_video_duration_matches_fps(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        result = combine([red_frame, blue_frame], 'video/mp4', fps=1.0)
        # 2 frames at 1 fps → ~2 s; allow ±0.5 s tolerance
        assert abs(result.duration - 2.0) < 0.5

    def test_combine_empty_raises_value_error(self):
        from madam.ffmpeg import combine

        with pytest.raises(ValueError):
            combine([], 'video/mp4', fps=1.0)

    def test_combine_unsupported_mime_type_raises(self, red_frame):
        from madam.ffmpeg import combine

        with pytest.raises(UnsupportedFormatError):
            combine([red_frame], 'image/png', fps=1.0)

    def test_combine_audio_mime_type_raises(self, red_frame):
        from madam.ffmpeg import combine

        with pytest.raises(UnsupportedFormatError):
            combine([red_frame], 'audio/mpeg', fps=1.0)

    def test_combine_accepts_generator(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        def gen():
            yield red_frame
            yield blue_frame

        result = combine(gen(), 'video/mp4', fps=1.0)
        assert isinstance(result, madam.core.Asset)

    def test_combine_webm_output(self, red_frame, blue_frame):
        from madam.ffmpeg import combine

        result = combine([red_frame, blue_frame], 'video/webm', fps=1.0)
        assert result.mime_type in ('video/webm', 'video/x-matroska')

    def test_combine_custom_codec(self, red_frame, blue_frame):
        from madam.ffmpeg import combine
        from madam.video import VideoCodec

        result = combine(
            [red_frame, blue_frame],
            'video/mp4',
            fps=1.0,
            video={'codec': VideoCodec.H264},
        )
        assert isinstance(result, madam.core.Asset)
