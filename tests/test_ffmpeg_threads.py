import multiprocessing
import unittest.mock

import pytest

from madam.ffmpeg import FFmpegProcessor


@pytest.fixture
def ffmpeg_version_ok(monkeypatch):
    """Patch subprocess so FFmpegProcessor.__init__ succeeds without real ffprobe."""
    mock_result = unittest.mock.MagicMock()
    mock_result.stdout = b'ffprobe version 6.0 Copyright ...'
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: mock_result)


class TestFFmpegThreadCount:
    def test_default_thread_count_equals_cpu_count(self, ffmpeg_version_ok):
        processor = FFmpegProcessor()
        assert processor._FFmpegProcessor__threads == multiprocessing.cpu_count()

    def test_thread_count_can_be_set_via_config(self, ffmpeg_version_ok):
        processor = FFmpegProcessor(config={'ffmpeg': {'threads': 2}})
        assert processor._FFmpegProcessor__threads == 2

    def test_thread_count_of_one_is_respected(self, ffmpeg_version_ok):
        processor = FFmpegProcessor(config={'ffmpeg': {'threads': 1}})
        assert processor._FFmpegProcessor__threads == 1

    def test_zero_threads_falls_back_to_cpu_count(self, ffmpeg_version_ok):
        processor = FFmpegProcessor(config={'ffmpeg': {'threads': 0}})
        assert processor._FFmpegProcessor__threads == multiprocessing.cpu_count()
