"""Tests for web/VOD quality and multi-processing performance optimizations."""

import io
import subprocess
import unittest.mock
import warnings

import PIL.Image
import pytest

import madam.image
from madam.ffmpeg import FFmpegProcessor


def _avif_supported() -> bool:
    try:
        buf = io.BytesIO()
        PIL.Image.new('RGB', (4, 4)).save(buf, 'AVIF')
        return True
    except Exception:
        return False


def _capture_ffmpeg_encode_commands(callable_):
    """Run callable_ while recording every ffmpeg (not ffprobe) command. Returns (result, [cmds])."""
    commands: list[list[str]] = []
    original_run = subprocess.run

    def tracking_run(cmd, *args, **kwargs):
        commands.append(list(cmd))
        return original_run(cmd, *args, **kwargs)

    with unittest.mock.patch('madam.ffmpeg.subprocess.run', tracking_run):
        result = callable_()

    encode_cmds = [c for c in commands if c and c[0] == 'ffmpeg']
    return result, encode_cmds


# ---------------------------------------------------------------------------
# MP4 / web streaming
# ---------------------------------------------------------------------------


class TestMP4FastStart:
    def test_mp4_output_has_moov_before_mdat_by_default(self, nut_video_asset):
        """MP4 must have moov atom before mdat for progressive web streaming (faststart)."""
        proc = FFmpegProcessor()
        convert = proc.convert(
            mime_type='video/mp4',
            video={'codec': 'libx264'},
            audio={'codec': 'aac'},
        )
        result = convert(nut_video_asset)
        data = result.essence.read()

        moov_pos = data.find(b'moov')
        mdat_pos = data.find(b'mdat')

        assert moov_pos >= 0, 'moov atom not found in MP4 output'
        assert mdat_pos >= 0, 'mdat atom not found in MP4 output'
        assert moov_pos < mdat_pos, (
            f'moov (byte {moov_pos}) must precede mdat (byte {mdat_pos}) '
            'for web streaming; apply -movflags +faststart'
        )

    def test_mp4_faststart_can_be_disabled_via_config(self, nut_video_asset):
        """Users can opt out of faststart by setting faststart=False in config."""
        proc = FFmpegProcessor(config={'video/mp4': {'faststart': False}})
        convert = proc.convert(
            mime_type='video/mp4',
            video={'codec': 'libx264'},
            audio={'codec': 'aac'},
        )
        result = convert(nut_video_asset)
        assert b'moov' in result.essence.read()


# ---------------------------------------------------------------------------
# H.264 (libx264) defaults
# ---------------------------------------------------------------------------


class TestH264Defaults:
    def test_h264_encode_command_includes_yuv420p(self, nut_video_asset):
        """H.264 must use yuv420p pixel format for broad browser/device compatibility."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/mp4', video={'codec': 'libx264'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-pix_fmt' in cmd
        idx = cmd.index('-pix_fmt')
        assert cmd[idx + 1] == 'yuv420p', f"Expected 'yuv420p', got '{cmd[idx + 1]}'"

    def test_h264_encode_command_uses_medium_preset(self, nut_video_asset):
        """H.264 default preset must be 'medium' (speed/quality balance for web/VOD)."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/mp4', video={'codec': 'libx264'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-preset' in cmd
        idx = cmd.index('-preset')
        assert cmd[idx + 1] == 'medium', f"Expected preset 'medium', got '{cmd[idx + 1]}'"

    def test_h264_encode_command_includes_high_profile(self, nut_video_asset):
        """H.264 must use High profile for best compression with broad device support."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/mp4', video={'codec': 'libx264'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-profile:v' in cmd
        idx = cmd.index('-profile:v')
        assert cmd[idx + 1] == 'high', f"Expected profile:v 'high', got '{cmd[idx + 1]}'"


# ---------------------------------------------------------------------------
# VP9 (libvpx-vp9) defaults
# ---------------------------------------------------------------------------


class TestVP9Defaults:
    def test_vp9_encode_command_includes_bv_zero(self, nut_video_asset):
        """VP9 CRF mode requires -b:v 0; without it, CRF is silently ignored."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/webm', video={'codec': 'libvpx-vp9'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-b:v' in cmd, '-b:v 0 required for VP9 constant-quality CRF mode'
        idx = cmd.index('-b:v')
        assert cmd[idx + 1] == '0', f"VP9 CRF mode needs -b:v 0, got -b:v {cmd[idx + 1]}"

    def test_vp9_encode_command_includes_tile_columns(self, nut_video_asset):
        """VP9 must use tile-columns for multi-core parallel encoding."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/webm', video={'codec': 'libvpx-vp9'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-tile-columns' in cmd, 'tile-columns required for VP9 multi-core encoding'

    def test_vp9_encode_command_includes_cpu_used(self, nut_video_asset):
        """VP9 must set cpu-used for speed/quality control (2 = VOD sweet spot)."""
        proc = FFmpegProcessor()
        _, cmds = _capture_ffmpeg_encode_commands(
            lambda: proc.convert(mime_type='video/webm', video={'codec': 'libvpx-vp9'})(nut_video_asset)
        )
        assert cmds, 'No ffmpeg encode command captured'
        cmd = cmds[0]
        assert '-cpu-used' in cmd


# ---------------------------------------------------------------------------
# AVIF image defaults
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _avif_supported(), reason='AVIF not supported in this environment')
class TestAVIFDefaults:
    def test_avif_default_speed_is_4(self):
        """AVIF default encoding speed must be 4 for better web compression quality."""
        proc = madam.image.PillowProcessor()

        buf = io.BytesIO()
        PIL.Image.new('RGB', (16, 16), (128, 64, 32)).save(buf, 'AVIF')
        buf.seek(0)
        asset = proc.read(buf)

        save_kwargs_list: list[dict] = []
        original_save = PIL.Image.Image.save

        def capturing_save(img_self, fp, format=None, **kwargs):
            save_kwargs_list.append({'format': format, 'kwargs': kwargs})
            return original_save(img_self, fp, format, **kwargs)

        with unittest.mock.patch.object(PIL.Image.Image, 'save', capturing_save):
            proc.convert(mime_type='image/avif')(asset)

        avif_saves = [c for c in save_kwargs_list if c['format'] == 'AVIF']
        assert avif_saves, 'No AVIF save call found'
        assert avif_saves[0]['kwargs'].get('speed') == 4, (
            f"Expected AVIF default speed=4, got speed={avif_saves[0]['kwargs'].get('speed')}"
        )


# ---------------------------------------------------------------------------
# JPEG subsampling config key
# ---------------------------------------------------------------------------


class TestJPEGSubsamplingConfig:
    def _make_jpeg(self) -> io.BytesIO:
        buf = io.BytesIO()
        PIL.Image.new('RGB', (8, 8), (200, 100, 50)).save(buf, 'JPEG')
        buf.seek(0)
        return buf

    def test_jpeg_subsampling_config_key_does_not_warn(self):
        """'subsampling' must be a valid JPEG config key — no UserWarning when set."""
        config = {'image/jpeg': {'subsampling': 0}}
        proc = madam.image.PillowProcessor(config)
        asset = proc.read(self._make_jpeg())

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            proc.convert(mime_type='image/jpeg')(asset)

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert not user_warnings, f'Unexpected UserWarning(s): {[str(x.message) for x in user_warnings]}'

    def test_jpeg_subsampling_0_produces_valid_jpeg(self):
        """subsampling=0 (4:4:4, no chroma subsampling) must produce a valid JPEG output."""
        config = {'image/jpeg': {'subsampling': 0}}
        proc = madam.image.PillowProcessor(config)
        asset = proc.read(self._make_jpeg())

        result = proc.convert(mime_type='image/jpeg')(asset)
        assert result.mime_type == 'image/jpeg'
        assert len(result.essence.read()) > 0
