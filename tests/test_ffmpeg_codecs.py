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
