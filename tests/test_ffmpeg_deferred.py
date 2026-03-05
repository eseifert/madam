"""Tests for deferred FFmpeg pipeline execution."""
import io
import json
import subprocess
import unittest.mock

import pytest

import madam.ffmpeg
from madam.core import Asset, Pipeline


class TestFFmpegFilterGraph:
    def test_filter_graph_is_importable(self):
        from madam.ffmpeg import FFmpegFilterGraph  # noqa: F401

    def test_starts_empty(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()

        assert g.video_filter_string == ''
        assert g.audio_filter_string == ''

    def test_add_video_filter_appends(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.add_video_filter('scale', w=640, h=480)

        assert 'scale' in g.video_filter_string

    def test_add_two_video_filters_joins_with_comma(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.add_video_filter('scale', w=640, h=480)
        g.add_video_filter('crop', w=320, h=240, x=0, y=0)

        parts = g.video_filter_string.split(',')
        assert len(parts) == 2
        assert parts[0].startswith('scale')
        assert parts[1].startswith('crop')

    def test_add_audio_filter_appends(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.add_audio_filter('volume', volume=0.5)

        assert 'volume' in g.audio_filter_string

    def test_set_output_format_stores_mime_type(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.set_output_format('video/mp4')

        assert g.output_mime_type == 'video/mp4'

    def test_set_codec_options_merges(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.set_codec_options(vcodec='libx264')
        g.set_codec_options(acodec='aac')

        assert g.codec_options.get('vcodec') == 'libx264'
        assert g.codec_options.get('acodec') == 'aac'

    def test_set_codec_options_raises_on_conflicting_same_key(self):
        from madam.ffmpeg import FFmpegFilterGraph

        g = FFmpegFilterGraph()
        g.set_codec_options(vcodec='libx264')

        with pytest.raises(ValueError):
            g.set_codec_options(vcodec='libvpx')


def _make_mock_processor(monkeypatch):
    """Return a real FFmpegProcessor with subprocess.run mocked."""
    probe_result = json.dumps({
        'format': {'format_name': 'matroska,webm', 'duration': '5.0'},
        'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 64, 'height': 64}],
    }).encode()
    mock_run = unittest.mock.MagicMock()
    mock_run.return_value.stdout = probe_result
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(subprocess, 'run', mock_run)
    return madam.ffmpeg.FFmpegProcessor(), mock_run


def _make_video_asset():
    return Asset(
        io.BytesIO(b'\x00' * 64),
        mime_type='video/x-matroska',
        width=64,
        height=64,
        duration=5.0,
        video={'codec': 'h264'},
        audio={},
    )


class TestFFmpegContext:
    def test_ffmpeg_context_is_importable(self):
        from madam.ffmpeg import FFmpegContext  # noqa: F401

    def test_ffmpeg_context_holds_asset_and_graph(self, monkeypatch):
        from madam.ffmpeg import FFmpegContext, FFmpegFilterGraph

        proc, _ = _make_mock_processor(monkeypatch)
        asset = _make_video_asset()
        graph = FFmpegFilterGraph()
        graph.set_output_format(asset.mime_type)

        ctx = FFmpegContext(proc, asset, graph)

        assert ctx.asset is asset
        assert ctx.graph is graph

    def test_ffmpeg_context_processor_returns_owning_processor(self, monkeypatch):
        from madam.ffmpeg import FFmpegContext, FFmpegFilterGraph

        proc, _ = _make_mock_processor(monkeypatch)
        asset = _make_video_asset()
        graph = FFmpegFilterGraph()
        graph.set_output_format(asset.mime_type)

        ctx = FFmpegContext(proc, asset, graph)

        assert ctx.processor is proc

    def test_ffmpeg_context_is_processing_context_subclass(self, monkeypatch):
        from madam.core import ProcessingContext
        from madam.ffmpeg import FFmpegContext

        assert issubclass(FFmpegContext, ProcessingContext)



class TestFFmpegDeferredExecution:
    def test_two_video_ops_spawn_single_subprocess(self, monkeypatch):
        """resize then crop in a Pipeline must spawn exactly one ffmpeg process."""
        probe_result = json.dumps({
            'format': {'format_name': 'matroska,webm', 'duration': '5.0'},
            'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 64, 'height': 64}],
        }).encode()

        call_log: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            call_log.append(list(cmd))
            result = unittest.mock.MagicMock()
            result.stdout = probe_result
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, 'run', fake_run)

        proc = madam.ffmpeg.FFmpegProcessor()
        asset = _make_video_asset()

        # Write fake matroska bytes to a temp file so _FFmpegContext can copy it.
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mkv') as f:
            f.write(b'\x00' * 64)
            tmp_path = f.name

        resize_op = proc.resize(width=32, height=32)
        crop_op = proc.crop(x=0, y=0, width=16, height=16)
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(crop_op)

        call_log.clear()  # reset: ignore __init__ probe calls

        try:
            list(pipeline.process(asset))
        except Exception:
            pass  # ignore materialisation failures from fake bytes

        os.unlink(tmp_path)

        # Count ffmpeg (not ffprobe) subprocess calls
        ffmpeg_calls = [c for c in call_log if c and c[0] == 'ffmpeg']
        assert len(ffmpeg_calls) == 1, (
            f'Expected 1 ffmpeg subprocess, got {len(ffmpeg_calls)}: {ffmpeg_calls}'
        )

    def test_single_ffmpeg_call_contains_both_filters(self, monkeypatch):
        """The combined ffmpeg call must include both the scale and crop filters."""
        probe_result = json.dumps({
            'format': {'format_name': 'matroska,webm', 'duration': '5.0'},
            'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 64, 'height': 64}],
        }).encode()

        call_log: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            call_log.append(list(cmd))
            result = unittest.mock.MagicMock()
            result.stdout = probe_result
            result.returncode = 0
            return result

        monkeypatch.setattr(subprocess, 'run', fake_run)

        proc = madam.ffmpeg.FFmpegProcessor()
        asset = _make_video_asset()

        resize_op = proc.resize(width=32, height=32)
        crop_op = proc.crop(x=0, y=0, width=16, height=16)
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(crop_op)

        call_log.clear()

        try:
            list(pipeline.process(asset))
        except Exception:
            pass

        ffmpeg_calls = [c for c in call_log if c and c[0] == 'ffmpeg']
        assert ffmpeg_calls, 'No ffmpeg calls recorded'
        combined_cmd = ' '.join(ffmpeg_calls[0])
        assert 'scale' in combined_cmd
        assert 'crop' in combined_cmd
