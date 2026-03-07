"""Tests for R05: VideoCodec and AudioCodec named constant classes."""


class TestVideoCodec:
    def test_importable_from_ffmpeg(self):
        from madam.ffmpeg import VideoCodec  # noqa: F401

    def test_importable_from_video(self):
        from madam.video import VideoCodec  # noqa: F401

    def test_h264_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.H264 == 'libx264'

    def test_h265_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.H265 == 'libx265'

    def test_vp8_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.VP8 == 'libvpx'

    def test_vp9_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.VP9 == 'libvpx-vp9'

    def test_av1_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.AV1 == 'libaom-av1'

    def test_copy_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.COPY == 'copy'

    def test_none_value(self):
        from madam.ffmpeg import VideoCodec

        assert VideoCodec.NONE is None


class TestAudioCodec:
    def test_importable_from_ffmpeg(self):
        from madam.ffmpeg import AudioCodec  # noqa: F401

    def test_importable_from_audio(self):
        from madam.audio import AudioCodec  # noqa: F401

    def test_aac_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.AAC == 'aac'

    def test_opus_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.OPUS == 'libopus'

    def test_vorbis_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.VORBIS == 'libvorbis'

    def test_mp3_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.MP3 == 'libmp3lame'

    def test_flac_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.FLAC == 'flac'

    def test_copy_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.COPY == 'copy'

    def test_none_value(self):
        from madam.ffmpeg import AudioCodec

        assert AudioCodec.NONE is None


class TestVideoAndAudioCodecSameObject:
    """video.VideoCodec and ffmpeg.VideoCodec must be the same class (re-export, not copy)."""

    def test_video_codec_is_same_class_as_ffmpeg_video_codec(self):
        from madam.ffmpeg import VideoCodec as FfmpegVC
        from madam.video import VideoCodec as VideoVC

        assert FfmpegVC is VideoVC

    def test_audio_codec_is_same_class_as_ffmpeg_audio_codec(self):
        from madam.audio import AudioCodec as AudioAC
        from madam.ffmpeg import AudioCodec as FfmpegAC

        assert FfmpegAC is AudioAC


class TestSubtitleFormat:
    def test_importable_from_ffmpeg(self):
        from madam.ffmpeg import SubtitleFormat  # noqa: F401

    def test_importable_from_subtitle(self):
        from madam.subtitle import SubtitleFormat  # noqa: F401

    def test_webvtt_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.WEBVTT == 'webvtt'

    def test_srt_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.SRT == 'subrip'

    def test_ass_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.ASS == 'ass'

    def test_ssa_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.SSA == 'ssa'

    def test_dvb_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.DVB == 'dvb_subtitle'

    def test_copy_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.COPY == 'copy'

    def test_none_value(self):
        from madam.ffmpeg import SubtitleFormat

        assert SubtitleFormat.NONE is None

    def test_subtitle_format_is_same_class_as_ffmpeg_subtitle_format(self):
        from madam.ffmpeg import SubtitleFormat as FfmpegSF
        from madam.subtitle import SubtitleFormat as SubSF

        assert FfmpegSF is SubSF


class TestSubtitleMimeTypes:
    def test_srt_mime_type_readable(self):
        """FFmpegProcessor must map text/x-subrip in supported_mime_types."""
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        assert 'text/x-subrip' in {str(m) for m in p.supported_mime_types}

    def test_ass_mime_type_readable(self):
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        assert 'text/x-ssa' in {str(m) for m in p.supported_mime_types}

    def test_webvtt_mime_type_readable(self):
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        assert 'text/vtt' in {str(m) for m in p.supported_mime_types}

    def test_read_srt_file_returns_asset(self):
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        with open('tests/resources/subtitle.srt', 'rb') as f:
            asset = p.read(f)
        assert asset.mime_type == 'text/x-subrip'

    def test_read_srt_file_has_subtitle_stream(self):
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        with open('tests/resources/subtitle.srt', 'rb') as f:
            asset = p.read(f)
        assert hasattr(asset, 'subtitle')
        assert asset.subtitle is not None

    def test_read_webvtt_returns_subtitle_codec(self):
        from madam.ffmpeg import FFmpegProcessor

        p = FFmpegProcessor()
        with open('tests/resources/subtitle.vtt', 'rb') as f:
            asset = p.read(f)
        assert asset.subtitle['codec'] == 'webvtt'
