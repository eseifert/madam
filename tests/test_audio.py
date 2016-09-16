import json
import subprocess

import pytest

import madam.audio
from madam.core import OperatorError
from madam.future import subprocess_run
from assets import audio_asset, mp3_asset, wav_asset


class TestMutagenProcessor:
    @pytest.fixture(name='processor')
    def mutagen_processor(self):
        return madam.audio.MutagenProcessor()

    def test_create_asset_from_mp3(self, processor):
        mp3_file_path = 'tests/resources/64kbits_with_id3v2-4.mp3'
        with open(mp3_file_path, 'rb') as mp3_file:
            asset = processor._read(mp3_file)
        assert asset.mime_type == 'audio/mpeg'
        assert asset.duration == pytest.approx(0.144, abs=0.01)
        assert asset.essence is not None
        assert asset.essence.read()

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
    def ffmpeg_processor(self):
        return madam.audio.FFmpegProcessor()

    def test_cannot_resize_audio(self, processor, audio_asset):
        resize_operator = processor.resize(width=12, height=34)

        with pytest.raises(OperatorError):
            resize_operator(audio_asset)

    def test_converted_essence_is_of_specified_type(self, processor, audio_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg')

        converted_asset = conversion_operator(audio_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'mp3'

    def test_converted_essence_stream_has_specified_codec(self, processor, audio_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg', audio=dict(codec='mp3'))

        converted_asset = conversion_operator(audio_asset)

        command = 'ffprobe -print_format json -loglevel error -show_streams -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('streams', [{}])[0].get('codec_name') == 'mp3'


class TestFFmpegProcessor:
    @pytest.fixture(name='processor')
    def ffmpeg_metadata_processor(self):
        return madam.audio.FFmpegMetadataProcessor()

    def test_supports_id3(self, processor):
        assert 'id3' in processor.formats

    def test_read_returns_correct_metadata_dict_for_mp3_with_id3(self, processor):
        with open('tests/resources/64kbits_with_id3v2-4.mp3', 'rb') as file:
            metadata = processor.read(file)

        assert metadata['id3']['artist'] == 'Frédéric Chopin'
        assert len(metadata) == 1

    def test_strip_returns_essence_without_metadata(self, processor):
        with open('tests/resources/64kbits_with_id3v2-4.mp3', 'rb') as file:
            essence = file.read()
            file.seek(0)
            stripped_essence = processor.strip(file).read()

        assert essence != stripped_essence
