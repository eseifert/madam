"""Tests for R06: FFmpegProcessor version check and graceful degradation."""
import subprocess
import unittest.mock

import pytest

from madam.ffmpeg import FFmpegProcessor, _parse_version


class TestParseVersion:
    def test_parses_simple_version(self):
        assert _parse_version('3.3') == (3, 3)

    def test_parses_three_part_version(self):
        assert _parse_version('6.1.2') == (6, 1, 2)

    def test_version_10_greater_than_3_3(self):
        assert _parse_version('10.0') > _parse_version('3.3')

    def test_version_3_3_not_greater_than_3_3(self):
        assert not (_parse_version('3.3') > _parse_version('3.3'))

    def test_version_3_2_less_than_3_3(self):
        assert _parse_version('3.2') < _parse_version('3.3')

    def test_invalid_version_raises_value_error(self):
        with pytest.raises(ValueError):
            _parse_version('not-a-version')


class TestFFmpegProcessorInit:
    @pytest.fixture
    def mock_ffprobe_ok(self, monkeypatch):
        result = unittest.mock.MagicMock()
        result.stdout = b'ffprobe version 6.1 Copyright (C) 2007-2023 the FFmpeg developers'
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: result)

    def test_raises_environment_error_when_ffprobe_not_found(self, monkeypatch):
        monkeypatch.setattr(
            'subprocess.run',
            unittest.mock.Mock(side_effect=FileNotFoundError),
        )
        with pytest.raises(EnvironmentError, match='not found'):
            FFmpegProcessor()

    def test_raises_environment_error_when_ffprobe_times_out(self, monkeypatch):
        monkeypatch.setattr(
            'subprocess.run',
            unittest.mock.Mock(side_effect=subprocess.TimeoutExpired('ffprobe', 10)),
        )
        with pytest.raises(EnvironmentError, match='timed out'):
            FFmpegProcessor()

    def test_raises_environment_error_for_version_below_minimum(self, monkeypatch):
        result = unittest.mock.MagicMock()
        result.stdout = b'ffprobe version 3.2 Copyright ...'
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: result)
        with pytest.raises(EnvironmentError, match='3.2'):
            FFmpegProcessor()

    def test_version_10_is_accepted(self, monkeypatch):
        result = unittest.mock.MagicMock()
        result.stdout = b'ffprobe version 10.0 Copyright ...'
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: result)
        proc = FFmpegProcessor()  # must not raise
        assert proc is not None

    def test_thread_count_is_evaluated_lazily(self, mock_ffprobe_ok):
        """_threads is a property, not a fixed value set at construction time."""
        proc = FFmpegProcessor()
        t1 = proc._threads
        t2 = proc._threads
        assert t1 == t2  # deterministic
        assert t1 > 0

    def test_configured_thread_count_is_respected(self, mock_ffprobe_ok):
        proc = FFmpegProcessor(config={'ffmpeg': {'threads': 4}})
        assert proc._threads == 4

    def test_zero_thread_config_falls_back_to_cpu_count(self, mock_ffprobe_ok):
        import multiprocessing
        proc = FFmpegProcessor(config={'ffmpeg': {'threads': 0}})
        assert proc._threads == multiprocessing.cpu_count()
