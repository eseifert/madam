"""Tests for R04: FFmpeg stderr sanitization in public OperatorError messages."""

import subprocess
import unittest.mock

import pytest

from madam.ffmpeg import _ffmpeg_error_message


class TestFfmpegErrorMessage:
    def test_returns_last_non_empty_line_of_stderr(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg'])
        error.stderr = b'first line\nsecond line\nactual error\n'
        msg = _ffmpeg_error_message(error, 'convert asset')
        assert msg == 'Could not convert asset: actual error'

    def test_skips_trailing_blank_lines(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg'])
        error.stderr = b'first line\nactual error\n\n\n'
        msg = _ffmpeg_error_message(error, 'resize asset')
        assert msg == 'Could not resize asset: actual error'

    def test_handles_empty_stderr(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg'])
        error.stderr = b''
        msg = _ffmpeg_error_message(error, 'trim asset')
        assert msg == 'Could not trim asset: unknown error'

    def test_handles_none_stderr(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg'])
        error.stderr = None
        msg = _ffmpeg_error_message(error, 'crop asset')
        assert msg == 'Could not crop asset: unknown error'

    def test_handles_non_utf8_stderr(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg'])
        error.stderr = b'\xff\xfe invalid utf-8\nreal error'
        msg = _ffmpeg_error_message(error, 'rotate asset')
        assert msg.startswith('Could not rotate asset:')


class TestOperatorErrorDoesNotLeakFullStderr:
    """OperatorError raised by operators must use _ffmpeg_error_message, not raw stderr."""

    @pytest.fixture
    def mock_ffprobe_ok(self, monkeypatch):
        result = unittest.mock.MagicMock()
        result.stdout = b'ffprobe version 6.1 Copyright (C) 2007-2023 the FFmpeg developers'
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: result)

    def test_operator_error_message_starts_with_could_not(self, mock_ffprobe_ok):
        """OperatorError from a failing FFmpeg call starts with 'Could not ...'."""
        import io

        from madam.core import Asset, OperatorError
        from madam.ffmpeg import FFmpegProcessor

        proc = FFmpegProcessor()

        # Build a minimal video asset with a real BytesIO essence so _FFmpegContext works
        asset = unittest.mock.MagicMock(spec=Asset)
        asset.mime_type = 'video/mp4'
        asset.width = 100
        asset.height = 100
        asset.essence = io.BytesIO(b'\x00' * 16)

        # Make the actual ffmpeg subprocess fail with a multi-line stderr
        def fake_run(*args, **kwargs):
            if 'ffprobe' in args[0][0]:
                r = unittest.mock.MagicMock()
                r.stdout = b'ffprobe version 6.1 Copyright ...'
                r.returncode = 0
                return r
            # ffmpeg encode call — raise with multi-line stderr
            err = subprocess.CalledProcessError(1, args[0])
            err.stderr = b'line1\nline2\nactual ffmpeg error'
            raise err

        import madam.ffmpeg

        with unittest.mock.patch.object(madam.ffmpeg.subprocess, 'run', side_effect=fake_run):
            with pytest.raises(OperatorError) as exc_info:
                resize_op = proc.resize(width=50, height=50)
                resize_op(asset)

        msg = str(exc_info.value)
        assert msg.startswith('Could not '), f'Expected "Could not ...", got: {msg!r}'
        # Full stderr must NOT appear verbatim
        assert 'line1\nline2' not in msg
