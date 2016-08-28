import json
import subprocess
from io import BytesIO

import pytest

import madam.video
from madam.future import subprocess_run
from assets import y4m_asset, unknown_asset


class TestFFmpegProcessor:
    @pytest.fixture(name='processor')
    def ffmpeg_processor(self):
        return madam.video.FFmpegProcessor()

    def test_supports_y4m_file(self, processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            supported = processor._can_read(video_file)

        assert supported

    def test_cannot_read_unknown_file(self, processor):
        random_data = b'\x07]>e\x10\n+Y\x07\xd8\xf4\x90%\r\xbbK\xb8+\xf3v%\x0f\x11'
        unknown_file = BytesIO(random_data)

        supported = processor._can_read(unknown_file)

        assert not supported

    def test_fails_with_invalid_file_object(self, processor):
        invalid_file = None

        with pytest.raises(ValueError):
            processor._can_read(invalid_file)

    def test_read_returns_asset_when_called_with_video_file(self, processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            asset = processor.read(video_file)

        assert asset is not None

    def test_read_returns_asset_with_filled_essence_when_called_with_video_file(self, processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            asset = processor.read(video_file)

        with open(video_path, 'rb') as video_file:
            assert asset.essence.read() == video_file.read()

    def test_read_returns_asset_of_correct_type(self, processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            asset = processor.read(video_file)

        assert asset.mime_type == 'video/x-yuv4mpegpipe'

    def test_read_returns_asset_with_duration_metadata(self, processor):
        video_path = 'tests/resources/bus_qcif_15fps.y4m'

        with open(video_path, 'rb') as video_file:
            asset = processor.read(video_file)

        assert asset.duration == 5.0

    def test_converted_asset_receives_correct_mime_type(self, processor, y4m_asset):
        conversion_operator = processor.convert(mime_type='video/webm')

        converted_asset = conversion_operator(y4m_asset)

        assert converted_asset.mime_type == 'video/webm'

    def test_convert_creates_new_asset(self, processor, y4m_asset):
        conversion_operator = processor.convert(mime_type='video/webm')

        converted_asset = conversion_operator(y4m_asset)

        assert isinstance(converted_asset, madam.core.Asset)
        assert converted_asset != y4m_asset

    def test_convert_raises_error_when_it_fails(self, processor, unknown_asset):
        conversion_operator = processor.convert(mime_type='video/webm')

        with pytest.raises(IOError):
            conversion_operator(unknown_asset)

    def test_converted_essence_is_of_specified_type(self, processor, y4m_asset):
        conversion_operator = processor.convert(mime_type='video/webm')

        converted_asset = conversion_operator(y4m_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'matroska,webm'
