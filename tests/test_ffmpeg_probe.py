"""Tests for the _probe() internal function in madam.ffmpeg."""
import io
import json
import subprocess
import tempfile
import unittest.mock

import pytest

from madam.ffmpeg import _probe


STDIN_PROBE_RESULT_WITH_DURATION = json.dumps({
    'format': {'format_name': 'ogg', 'duration': '0.2'},
    'streams': [{'codec_type': 'audio', 'codec_name': 'opus'}],
}).encode()

STDIN_PROBE_RESULT_WITHOUT_DURATION = json.dumps({
    'format': {'format_name': 'ogg'},
    'streams': [{'codec_type': 'audio', 'codec_name': 'opus'}],
}).encode()


class TestProbeContract:
    """_probe() must always try stdin first and fall back only when needed."""

    def test_probe_always_calls_subprocess_with_stdin_input(self):
        """The very first subprocess.run() call must use input= (i.e. stdin)."""
        with open('tests/resources/64kbits_with_id3v2-4.mp3', 'rb') as f:
            file = io.BytesIO(f.read())

        call_args_list: list[dict] = []
        real_run = subprocess.run

        def tracking_run(*args, **kwargs):
            call_args_list.append({'args': args, 'kwargs': kwargs})
            return real_run(*args, **kwargs)

        with unittest.mock.patch('madam.ffmpeg.subprocess.run', tracking_run):
            _probe(file)

        assert call_args_list, 'subprocess.run() was never called'
        first_call_kwargs = call_args_list[0]['kwargs']
        assert 'input' in first_call_kwargs, (
            'First subprocess.run() call must pass data via stdin (input=); '
            f'actual kwargs: {list(first_call_kwargs.keys())}'
        )

    def test_probe_uses_no_temp_file_when_stdin_provides_duration(self):
        """When stdin probe returns duration, no NamedTemporaryFile is created."""
        file = io.BytesIO(b'fake-data')

        created_temp_files: list[str] = []
        real_named_tmpfile = tempfile.NamedTemporaryFile

        def tracking_named_tmpfile(*args, **kwargs):
            tmp = real_named_tmpfile(*args, **kwargs)
            created_temp_files.append(tmp.name)
            return tmp

        mock_result = unittest.mock.MagicMock()
        mock_result.stdout = STDIN_PROBE_RESULT_WITH_DURATION

        with (
            unittest.mock.patch('madam.ffmpeg.subprocess.run', return_value=mock_result),
            unittest.mock.patch('madam.ffmpeg.tempfile.NamedTemporaryFile', tracking_named_tmpfile),
        ):
            result = _probe(file)

        assert created_temp_files == [], (
            'No NamedTemporaryFile should be created when stdin probe includes duration; '
            f'created: {created_temp_files}'
        )
        assert result['format']['duration'] == '0.2'

    def test_probe_falls_back_to_temp_file_when_stdin_omits_duration(self):
        """When stdin probe lacks duration, _probe() retries via a named temp file."""
        file = io.BytesIO(b'fake-data')

        created_temp_files: list[str] = []
        real_named_tmpfile = tempfile.NamedTemporaryFile

        def tracking_named_tmpfile(*args, **kwargs):
            tmp = real_named_tmpfile(*args, **kwargs)
            created_temp_files.append(tmp.name)
            return tmp

        # First call (stdin) omits duration; second call (temp file) provides it.
        fallback_result = json.dumps({
            'format': {'format_name': 'ogg', 'duration': '0.2'},
            'streams': [],
        }).encode()
        side_effects = [
            unittest.mock.MagicMock(stdout=STDIN_PROBE_RESULT_WITHOUT_DURATION),
            unittest.mock.MagicMock(stdout=fallback_result),
        ]

        with (
            unittest.mock.patch('madam.ffmpeg.subprocess.run', side_effect=side_effects),
            unittest.mock.patch('madam.ffmpeg.tempfile.NamedTemporaryFile', tracking_named_tmpfile),
        ):
            result = _probe(file)

        assert len(created_temp_files) == 1, (
            f'Expected exactly one fallback temp file; got: {created_temp_files}'
        )
        assert result['format']['duration'] == '0.2'

    def test_probe_returns_correct_metadata_for_mp3(self):
        """End-to-end: probe an MP3 and get back the expected format info."""
        with open('tests/resources/64kbits_with_id3v2-4.mp3', 'rb') as f:
            file = io.BytesIO(f.read())

        result = _probe(file)

        assert 'format' in result
        assert 'streams' in result
        assert result['format']['format_name'] == 'mp3'
        assert 'duration' in result['format']

    def test_probe_resets_file_position_to_zero(self):
        """_probe() must leave the file-like object at position 0."""
        with open('tests/resources/64kbits_with_id3v2-4.mp3', 'rb') as f:
            file = io.BytesIO(f.read())

        _probe(file)

        assert file.tell() == 0
