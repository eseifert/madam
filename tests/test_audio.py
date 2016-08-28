import pytest

import madam.audio


class TestWaveProcessor:
    @pytest.fixture(name='processor')
    def wave_processor(self):
        return madam.audio.WaveProcessor()

    def test_create_asset_from_wav(self, processor):
        asset = processor._read('tests/resources/16-bit-mono.wav')
        assert asset.mime_type == 'audio/wav'
        assert asset.framerate == 48000
        assert asset.channels == 1
        assert asset.essence is not None
        assert asset.essence.read()


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
