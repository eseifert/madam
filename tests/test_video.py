from io import BytesIO
import pytest

import madam.video


class TestFFmpegProcessor:
    @pytest.fixture
    def ffmpeg_processor(self):
        return madam.video.FFmpegProcessor()

    def test_supports_y4m_file(self, ffmpeg_processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            supported = ffmpeg_processor.can_read(video_file)

        assert supported

    def test_cannot_read_unknown_file(self, ffmpeg_processor):
        random_data = b'\x07]>e\x10\n+Y\x07\xd8\xf4\x90%\r\xbbK\xb8+\xf3v%\x0f\x11'
        unknown_file = BytesIO(random_data)

        supported = ffmpeg_processor.can_read(unknown_file)

        assert not supported

    def test_fails_with_invalid_file_object(self, ffmpeg_processor):
        invalid_file = None

        with pytest.raises(ValueError):
            ffmpeg_processor.can_read(invalid_file)

    def test_read_returns_asset_when_called_with_video_file(self, ffmpeg_processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            asset = ffmpeg_processor.read(video_file)

        assert asset is not None
