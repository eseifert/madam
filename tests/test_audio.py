import json
import subprocess

import pytest

import madam.audio
from madam.future import subprocess_run
from assets import wav_asset


class TestMutagenProcessor:
    @pytest.fixture(name='processor')
    def mutagen_processor(self):
        return madam.audio.MutagenProcessor()

    def test_create_asset_from_mp3(self, processor):
        mp3_file_path = 'tests/resources/64kbits.mp3'
        with open(mp3_file_path, 'rb') as mp3_file:
            asset = processor._read(mp3_file)
        assert asset.mime_type == 'audio/mpeg'
        assert asset.duration == 0.1
        assert asset.essence is not None
        assert asset.essence.read()

        # Assert that essence was stripped from metadata
        with open(mp3_file_path, 'rb') as mp3_file:
            assert asset.essence.read() != mp3_file.read()

    def test_mp3_reader_does_not_change_file(self, processor):
        mp3_file_path = 'tests/resources/64kbits.mp3'
        with open(mp3_file_path, 'rb') as mp3_file:
            expected_data = mp3_file.read()
        with open(mp3_file_path, 'rb') as mp3_file:
            processor._read(mp3_file)
        with open(mp3_file_path, 'rb') as mp3_file:
            actual_data = mp3_file.read()
        assert expected_data == actual_data


class TestFFmpegProcessor:
    @pytest.fixture(name='processor')
    def mutagen_processor(self):
        return madam.audio.FFmpegProcessor()

    def test_create_asset_from_mp3(self, processor):
        mp3_file_path = 'tests/resources/64kbits.mp3'
        with open(mp3_file_path, 'rb') as mp3_file:
            asset = processor._read(mp3_file)
        assert asset.mime_type == 'audio/mpeg'
        assert asset.duration > 0
        assert asset.essence is not None
        assert asset.essence.read()

    def test_converted_essence_is_of_specified_type(self, processor, wav_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg')

        converted_asset = conversion_operator(wav_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'mp3'

    def test_converted_essence_stream_has_specified_codec(self, processor, wav_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg', audio=dict(codec='mp3'))

        converted_asset = conversion_operator(wav_asset)

        command = 'ffprobe -print_format json -loglevel error -show_streams -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('streams', [{}])[0].get('codec_name') == 'mp3'
