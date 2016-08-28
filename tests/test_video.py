import json
import subprocess
from io import BytesIO

import pytest

import madam.video
from madam.core import OperatorError
from madam.future import subprocess_run
from assets import y4m_asset, unknown_asset


class TestFFmpegProcessor:
    @pytest.fixture(name='processor')
    def ffmpeg_processor(self):
        return madam.video.FFmpegProcessor()

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

        with pytest.raises(OperatorError):
            conversion_operator(unknown_asset)

    def test_converted_essence_is_of_specified_type(self, processor, y4m_asset):
        conversion_operator = processor.convert(mime_type='video/webm')

        converted_asset = conversion_operator(y4m_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'matroska,webm'
