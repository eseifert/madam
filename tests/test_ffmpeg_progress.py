"""Tests for FFmpeg progress callback support."""

import io
import unittest.mock

import pytest

from madam.core import Asset
from madam.ffmpeg import FFmpegProcessor


@pytest.fixture
def ffmpeg_version_ok(monkeypatch):
    mock_result = unittest.mock.MagicMock()
    mock_result.stdout = b'ffprobe version 6.0 Copyright ...'
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: mock_result)


@pytest.fixture
def ogg_asset():
    # Minimal valid-ish OGG payload (just enough bytes to identify)
    return Asset(io.BytesIO(b'OggS\x00' + b'\x00' * 22), mime_type='audio/ogg', duration=1.0)


def _make_fake_popen(progress_lines: list[str], returncode: int = 0):
    """Build a fake Popen that writes FFmpeg-style progress lines to stdout."""
    progress_bytes = '\n'.join(progress_lines + ['progress=end']).encode()

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = io.BytesIO(progress_bytes)
            self.stderr = io.BytesIO(b'')
            self.returncode = returncode

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.wait()

        def wait(self):
            return self.returncode

        def poll(self):
            return self.returncode

    return FakePopen


class TestFFmpegProgressCallback:
    def test_convert_accepts_progress_callback_kwarg(self, monkeypatch, ffmpeg_version_ok):
        """progress_callback must be accepted without error (even if no actual FFmpeg)."""
        processor = FFmpegProcessor()
        callback = unittest.mock.MagicMock()
        op = processor.convert(mime_type='audio/ogg', progress_callback=callback)
        assert callable(op)

    def test_progress_callback_is_called_during_convert(self, monkeypatch, ffmpeg_version_ok):
        processor = FFmpegProcessor()
        received = []

        FakePopen = _make_fake_popen(
            [
                'frame=10',
                'fps=25.0',
                'bitrate=128.0kbits/s',
                'out_time=00:00:00.400000',
            ]
        )
        monkeypatch.setattr('subprocess.Popen', FakePopen)

        # Also patch the read-back so the Asset can be constructed from result
        fake_asset = Asset(io.BytesIO(b'result'), mime_type='audio/ogg')
        monkeypatch.setattr(processor, 'read', lambda _file: fake_asset)

        asset = Asset(io.BytesIO(b'input'), mime_type='audio/ogg', duration=1.0)
        op = processor.convert(mime_type='audio/ogg', progress_callback=received.append)
        op(asset)

        assert len(received) > 0

    def test_progress_callback_receives_dict_with_known_keys(self, monkeypatch, ffmpeg_version_ok):
        processor = FFmpegProcessor()
        received = []

        FakePopen = _make_fake_popen(
            [
                'frame=42',
                'fps=30.0',
                'out_time=00:00:01.400000',
            ]
        )
        monkeypatch.setattr('subprocess.Popen', FakePopen)

        fake_asset = Asset(io.BytesIO(b'result'), mime_type='audio/ogg')
        monkeypatch.setattr(processor, 'read', lambda _file: fake_asset)

        asset = Asset(io.BytesIO(b'input'), mime_type='audio/ogg', duration=1.0)
        op = processor.convert(mime_type='audio/ogg', progress_callback=received.append)
        op(asset)

        assert any('frame' in d for d in received)

    def test_convert_without_progress_callback_uses_subprocess_run(self, monkeypatch, ffmpeg_version_ok):
        """When no progress_callback is given, Popen must NOT be used."""
        processor = FFmpegProcessor()
        popen_called = []

        def fake_popen(*a, **kw):
            popen_called.append(True)

        monkeypatch.setattr('subprocess.Popen', fake_popen)

        run_called = []

        def fake_run(cmd, **kw):
            run_called.append(cmd)
            result = unittest.mock.MagicMock()
            result.returncode = 0
            result.stdout = b''
            result.stderr = b''
            return result

        monkeypatch.setattr('subprocess.run', fake_run)

        fake_asset = Asset(io.BytesIO(b'result'), mime_type='audio/ogg')
        monkeypatch.setattr(processor, 'read', lambda _file: fake_asset)

        asset = Asset(io.BytesIO(b'input'), mime_type='audio/ogg', duration=1.0)
        op = processor.convert(mime_type='audio/ogg')
        try:
            op(asset)
        except Exception:
            pass  # May fail due to missing file paths, we only care about popen_called

        assert not popen_called

    def test_progress_callback_raises_operator_error_on_ffmpeg_failure(self, monkeypatch, ffmpeg_version_ok):
        processor = FFmpegProcessor()

        FakePopen = _make_fake_popen([], returncode=1)
        monkeypatch.setattr('subprocess.Popen', FakePopen)

        asset = Asset(io.BytesIO(b'input'), mime_type='audio/ogg', duration=1.0)
        op = processor.convert(mime_type='audio/ogg', progress_callback=lambda d: None)

        from madam.core import OperatorError

        with pytest.raises(OperatorError):
            op(asset)
