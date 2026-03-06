"""Integration tests for deferred pipeline execution."""

from __future__ import annotations

import io
import json
import subprocess
import unittest.mock

import PIL.Image
import pytest

import madam.image
from madam.core import Asset, Pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jpeg_asset(width: int, height: int, quality: int = 95) -> Asset:
    """Create a simple JPEG Asset with a gradient pattern."""
    img = PIL.Image.new('RGB', (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (x * 255 // width, y * 255 // height, 128)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    buf.seek(0)
    proc = madam.image.PillowProcessor()
    return proc.read(buf)


def _pixel_sum_diff(asset_a: Asset, asset_b: Asset) -> float:
    """Return the sum of absolute pixel differences between two image assets."""
    asset_a.essence.seek(0)
    asset_b.essence.seek(0)
    with PIL.Image.open(asset_a.essence) as img_a, PIL.Image.open(asset_b.essence) as img_b:
        img_a = img_a.convert('RGB')
        img_b = img_b.convert('RGB').resize(img_a.size)
        raw_a = img_a.tobytes()
        raw_b = img_b.tobytes()
    total = sum(abs(a - b) for a, b in zip(raw_a, raw_b))
    return total


class TestImageQualityRegression:
    """Deferred pipeline must not degrade quality more than a single encode."""

    @pytest.fixture(name='processor')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_deferred_pipeline_matches_single_encode_dimensions(self, processor):
        """Three chained Pillow operators in a Pipeline produce correct dimensions."""
        asset = _jpeg_asset(128, 128, quality=90)

        pipeline = Pipeline()
        pipeline.add(processor.resize(width=64, height=64))
        pipeline.add(processor.crop(width=48, height=48, x=8, y=8))

        results = list(pipeline.process(asset))

        assert results[0].width == 48
        assert results[0].height == 48
        assert results[0].mime_type == 'image/jpeg'

    def test_deferred_pipeline_has_less_quality_loss_than_sequential(self, processor):
        """Deferred (one encode) must produce less pixel error than sequential (three encodes)."""
        source = _jpeg_asset(128, 128, quality=95)

        # Ground truth: apply operations directly on PIL image (no intermediate JPEG encodes).
        source.essence.seek(0)
        with PIL.Image.open(source.essence) as img:
            gt_img = img.convert('RGB')
            gt_img = gt_img.resize((64, 64), PIL.Image.Resampling.LANCZOS)
            gt_img = gt_img.crop((8, 8, 56, 56))  # 48×48 region
        gt_buf = io.BytesIO()
        gt_img.save(gt_buf, 'JPEG', quality=95)
        gt_buf.seek(0)
        ground_truth = processor.read(gt_buf)

        # Sequential path: three separate operator calls (three JPEG encodes).
        step1 = processor.resize(width=64, height=64)
        step2 = processor.crop(width=48, height=48, x=8, y=8)
        sequential = step2(step1(source))

        # Deferred path: Pipeline (one JPEG encode).
        pipeline = Pipeline()
        pipeline.add(processor.resize(width=64, height=64))
        pipeline.add(processor.crop(width=48, height=48, x=8, y=8))
        deferred = list(pipeline.process(source))[0]

        error_sequential = _pixel_sum_diff(ground_truth, sequential)
        error_deferred = _pixel_sum_diff(ground_truth, deferred)

        assert error_deferred <= error_sequential, (
            f'Deferred pipeline pixel error ({error_deferred}) should be ≤ sequential error '
            f'({error_sequential}) since deferred encodes once while sequential encodes twice.'
        )

    def test_deferred_pipeline_mime_type_preserved_across_three_ops(self, processor):
        """MIME type is preserved through three chained operators."""
        asset = _jpeg_asset(96, 96, quality=90)

        pipeline = Pipeline()
        pipeline.add(processor.resize(width=64, height=64))
        pipeline.add(processor.crop(width=32, height=32, x=16, y=16))
        pipeline.add(processor.rotate(angle=90, expand=True))

        results = list(pipeline.process(asset))

        assert results[0].mime_type == 'image/jpeg'


def _probe_json_video():
    return json.dumps(
        {
            'format': {'format_name': 'matroska,webm', 'duration': '10.0'},
            'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 128, 'height': 128}],
        }
    ).encode()


def _probe_json_audio():
    return json.dumps(
        {
            'format': {'format_name': 'ogg', 'duration': '10.0'},
            'streams': [{'codec_type': 'audio', 'codec_name': 'opus'}],
        }
    ).encode()


def _make_fake_run(call_log, probe_json):
    def fake_run(cmd, *args, **kwargs):
        call_log.append(list(cmd))
        result = unittest.mock.MagicMock()
        result.returncode = 0
        if cmd and 'ffprobe' in cmd[0]:
            if '-version' in cmd:
                result.stdout = b'ffprobe version 6.1 Copyright (C) 2007-2023 the FFmpeg developers'
            else:
                result.stdout = probe_json
        else:
            result.stdout = probe_json
        return result

    return fake_run


class TestFFmpegSubprocessCount:
    """Three chained FFmpeg operators must spawn exactly one ffmpeg subprocess."""

    def test_three_video_ops_spawn_single_subprocess(self, monkeypatch):
        import madam.ffmpeg

        probe_json = _probe_json_video()
        call_log: list[list[str]] = []
        monkeypatch.setattr(subprocess, 'run', _make_fake_run(call_log, probe_json))

        proc = madam.ffmpeg.FFmpegProcessor()
        asset = Asset(
            io.BytesIO(b'\x00' * 64),
            mime_type='video/x-matroska',
            width=128,
            height=128,
            duration=10.0,
            video={'codec': 'h264'},
            audio={},
        )
        pipeline = Pipeline()
        pipeline.add(proc.resize(width=64, height=64))
        pipeline.add(proc.crop(x=0, y=0, width=32, height=32))
        pipeline.add(proc.resize(width=16, height=16))

        call_log.clear()  # ignore __init__ probe calls

        try:
            list(pipeline.process(asset))
        except Exception:
            pass  # ignore materialisation failures from fake bytes

        ffmpeg_calls = [c for c in call_log if c and c[0] == 'ffmpeg']
        assert len(ffmpeg_calls) == 1, f'Expected 1 ffmpeg subprocess for three video ops, got {len(ffmpeg_calls)}'

    def test_three_video_ops_combined_command_contains_all_filters(self, monkeypatch):
        import madam.ffmpeg

        probe_json = _probe_json_video()
        call_log: list[list[str]] = []
        monkeypatch.setattr(subprocess, 'run', _make_fake_run(call_log, probe_json))

        proc = madam.ffmpeg.FFmpegProcessor()
        asset = Asset(
            io.BytesIO(b'\x00' * 64),
            mime_type='video/x-matroska',
            width=128,
            height=128,
            duration=10.0,
            video={'codec': 'h264'},
            audio={},
        )
        pipeline = Pipeline()
        pipeline.add(proc.resize(width=64, height=64))
        pipeline.add(proc.crop(x=0, y=0, width=32, height=32))
        pipeline.add(proc.resize(width=16, height=16))

        call_log.clear()

        try:
            list(pipeline.process(asset))
        except Exception:
            pass

        ffmpeg_calls = [c for c in call_log if c and c[0] == 'ffmpeg']
        assert ffmpeg_calls, 'No ffmpeg calls recorded'
        combined = ' '.join(ffmpeg_calls[0])
        # All three scale/crop filters must appear in the combined command.
        assert combined.count('scale') == 2, f'Expected 2 scale filters in: {combined}'
        assert 'crop' in combined

    def test_flush_between_video_ops_forces_two_subprocesses(self, monkeypatch):
        import madam.ffmpeg

        probe_json = _probe_json_video()
        call_log: list[list[str]] = []
        monkeypatch.setattr(subprocess, 'run', _make_fake_run(call_log, probe_json))

        proc = madam.ffmpeg.FFmpegProcessor()
        asset = Asset(
            io.BytesIO(b'\x00' * 64),
            mime_type='video/x-matroska',
            width=128,
            height=128,
            duration=10.0,
            video={'codec': 'h264'},
            audio={},
        )
        pipeline = Pipeline()
        pipeline.add(proc.resize(width=64, height=64))
        pipeline.add(Pipeline.flush())
        pipeline.add(proc.crop(x=0, y=0, width=32, height=32))

        call_log.clear()

        try:
            list(pipeline.process(asset))
        except Exception:
            pass

        ffmpeg_calls = [c for c in call_log if c and c[0] == 'ffmpeg']
        assert len(ffmpeg_calls) == 2, (
            f'Expected 2 ffmpeg subprocesses (flush forces boundary), got {len(ffmpeg_calls)}'
        )


class TestRoundTripCorrectness:
    """Pipeline output must match direct operator application for dimensions, MIME, metadata."""

    @pytest.fixture(name='processor')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_pillow_pipeline_matches_direct_application_dimensions(self, processor):
        """Pipeline(resize → crop) must produce the same dimensions as direct resize(crop(asset))."""
        asset = _jpeg_asset(128, 64, quality=90)
        resize_op = processor.resize(width=64, height=32)
        crop_op = processor.crop(width=48, height=24, x=8, y=4)

        # Direct application.
        direct = crop_op(resize_op(asset))

        # Pipeline application.
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(crop_op)
        deferred = list(pipeline.process(asset))[0]

        assert deferred.width == direct.width
        assert deferred.height == direct.height
        assert deferred.mime_type == direct.mime_type

    def test_pillow_pipeline_convert_matches_direct_mime_type(self, processor):
        """Pipeline(resize → convert to PNG) produces the same MIME type as direct call."""
        asset = _jpeg_asset(64, 64, quality=90)
        resize_op = processor.resize(width=32, height=32)
        convert_op = processor.convert(mime_type='image/png')

        direct = convert_op(resize_op(asset))

        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(convert_op)
        deferred = list(pipeline.process(asset))[0]

        assert deferred.mime_type == direct.mime_type
        assert deferred.width == direct.width
        assert deferred.height == direct.height

    def test_svg_pipeline_matches_direct_application(self):
        """Pipeline(shrink → shrink) produces same SVG as calling shrink twice directly."""
        from madam.vector import SVGProcessor

        svg_content = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            b'  <rect width="0" height="0" />'
            b'  <circle r="0" />'
            b'  <text></text>'
            b'</svg>'
        )
        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(svg_content))
        shrink_op = proc.shrink()

        # Direct: apply twice.
        direct = shrink_op(shrink_op(asset))

        # Pipeline: apply twice in one run.
        pipeline = Pipeline()
        pipeline.add(shrink_op)
        pipeline.add(shrink_op)
        deferred = list(pipeline.process(asset))[0]

        assert deferred.mime_type == direct.mime_type
        assert deferred.width == direct.width
        assert deferred.height == direct.height

    def test_pillow_pipeline_three_ops_same_result_as_direct(self, processor):
        """Three-op Pipeline produces same dimensions as three sequential direct calls."""
        asset = _jpeg_asset(96, 96, quality=90)
        rotate_op = processor.rotate(angle=90, expand=True)
        resize_op = processor.resize(width=48, height=48)
        crop_op = processor.crop(width=32, height=32, x=8, y=8)

        # Direct.
        direct = crop_op(resize_op(rotate_op(asset)))

        # Pipeline.
        pipeline = Pipeline()
        pipeline.add(rotate_op)
        pipeline.add(resize_op)
        pipeline.add(crop_op)
        deferred = list(pipeline.process(asset))[0]

        assert deferred.width == direct.width
        assert deferred.height == direct.height
        assert deferred.mime_type == direct.mime_type
