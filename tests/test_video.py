import pytest

import madam.video


@pytest.fixture
def ffmpeg_processor():
    return madam.video.FFmpegProcessor()


def test_supports_y4m_file(ffmpeg_processor):
    video_path = 'tests/bus_qcif_15fps.y4m'

    with open(video_path, 'rb') as video_file:
        supported = ffmpeg_processor.can_read(video_file)

    assert supported


def test_read_returns_asset_when_called_with_video_file(ffmpeg_processor):
    video_path = 'tests/bus_qcif_15fps.y4m'

    with open(video_path, 'rb') as video_file:
        asset = ffmpeg_processor.read(video_file)

    assert asset is not None
