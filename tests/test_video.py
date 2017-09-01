import json
import subprocess
from collections import defaultdict

import PIL.Image
import pytest

import madam.video
from madam.core import OperatorError, UnsupportedFormatError
from madam.future import subprocess_run
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_DURATION
from assets import image_asset, jpeg_asset, png_asset, gif_asset
from assets import video_asset, mp4_asset, mkv_video_asset, ogg_video_asset
from assets import unknown_asset


class TestFFmpegProcessor:
    @pytest.fixture(name='processor', scope='class')
    def ffmpeg_processor(self):
        return madam.video.FFmpegProcessor()

    def __probe_streams_by_type(self, converted_asset):
        command = 'ffprobe -print_format json -loglevel error -show_streams -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        ffprobe_info = json.loads(result.stdout.decode('utf-8'))

        streams_by_type = defaultdict(list)
        for stream in ffprobe_info.get('streams', []):
            streams_by_type[stream['codec_type']].append(stream)

        return streams_by_type

    def test_resize_raises_error_for_invalid_dimensions(self, processor, video_asset):
        resize = processor.resize(width=12, height=-34)

        with pytest.raises(ValueError):
            resize(video_asset)

    def test_resize_returns_asset_with_correct_dimensions(self, processor, video_asset):
        resize = processor.resize(width=12, height=34)

        resized_asset = resize(video_asset)

        assert resized_asset.width == 12
        assert resized_asset.height == 34

    def test_resize_returns_essence_with_same_format(self, processor, mkv_video_asset):
        resize = processor.resize(width=12, height=34)

        resized_asset = resize(mkv_video_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=resized_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'matroska,webm'

    def test_resize_returns_essence_with_correct_dimensions(self, processor, video_asset):
        resize_operator = processor.resize(width=12, height=34)

        resized_asset = resize_operator(video_asset)

        command = 'ffprobe -print_format json -loglevel error -show_streams -i pipe:'.split()
        result = subprocess_run(command, input=resized_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        first_stream = video_info.get('streams', [{}])[0]
        assert first_stream.get('width') == 12
        assert first_stream.get('height') == 34

    def test_resize_raises_error_for_unknown_formats(self, processor, unknown_asset):
        resize_operator = processor.resize(width=12, height=34)

        with pytest.raises(UnsupportedFormatError):
            resize_operator(unknown_asset)

    @pytest.fixture(scope='class')
    def converted_asset(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='video/x-matroska',
                                                video=dict(codec='vp9', bitrate=50),
                                                audio=dict(codec='libopus', bitrate=16))
        converted_asset = conversion_operator(video_asset)
        return converted_asset

    def test_converted_asset_receives_correct_mime_type(self, converted_asset):
        assert converted_asset.mime_type == 'video/x-matroska'

    def test_convert_creates_new_asset(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='video/x-matroska')

        converted_asset = conversion_operator(video_asset)

        assert isinstance(converted_asset, madam.core.Asset)
        assert converted_asset != video_asset

    def test_convert_raises_error_when_it_fails(self, processor, unknown_asset):
        conversion_operator = processor.convert(mime_type='video/x-matroska')

        with pytest.raises(OperatorError):
            conversion_operator(unknown_asset)

    def test_converted_essence_is_of_specified_type(self, converted_asset):
        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=converted_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert video_info.get('format', {}).get('format_name') == 'matroska,webm'

    def test_converted_essence_stream_has_specified_codecs(self, converted_asset):
        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        assert len(video_streams) == 1
        assert video_streams[0]['codec_name'] == 'vp9'
        assert len(audio_streams) == 1
        assert audio_streams[0]['codec_name'] == 'opus'

    def test_converted_essence_stream_has_same_size_as_source(self, converted_asset):
        assert converted_asset.width == DEFAULT_WIDTH
        assert converted_asset.height == DEFAULT_HEIGHT

    def test_converted_essence_stream_has_same_duration_as_source(self, converted_asset):
        assert converted_asset.duration == pytest.approx(DEFAULT_DURATION, rel=1e-2)

    def test_convert_can_strip_audio_stream(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='video/quicktime',
                                                video=dict(codec='h264', bitrate=50),
                                                audio=dict(codec=None))

        converted_asset = conversion_operator(video_asset)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        assert len(video_streams) == 1
        assert video_streams[0]['codec_name'] == 'h264'
        assert len(audio_streams) == 0

    def test_convert_can_strip_video_stream(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg',
                                                video=dict(codec=None),
                                                audio=dict(codec='mp3', bitrate=32))

        converted_asset = conversion_operator(video_asset)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        assert len(video_streams) == 0
        assert len(audio_streams) == 1
        assert audio_streams[0]['codec_name'] == 'mp3'

    def test_trim_fails_for_image_assets(self, processor, image_asset):
        trim_operator = processor.trim(from_seconds=0, to_seconds=0.1)

        with pytest.raises(UnsupportedFormatError):
            trim_operator(image_asset)

    def test_trim_fails_when_start_time_is_after_end_time(self, processor, video_asset):
        trim_operator = processor.trim(from_seconds=0.2, to_seconds=0.1)

        with pytest.raises(ValueError):
            trim_operator(video_asset)

    def test_trimmed_asset_receives_correct_mime_type(self, processor, video_asset):
        mime_type = video_asset.mime_type
        trim_operator = processor.trim(from_seconds=0, to_seconds=0.1)

        trimmed_asset = trim_operator(video_asset)

        assert trimmed_asset.mime_type == mime_type

    def test_trimmed_asset_receives_correct_duration(self, processor, video_asset):
        trim_operator = processor.trim(from_seconds=0.0, to_seconds=0.1)

        trimmed_asset = trim_operator(video_asset)

        assert trimmed_asset.duration != video_asset.duration
        assert trimmed_asset.duration == 0.1

    def test_trimmed_asset_contains_valid_essence(self, processor, video_asset):
        trim_operator = processor.trim(from_seconds=0, to_seconds=0.1)

        trimmed_asset = trim_operator(video_asset)

        command = 'ffprobe -print_format json -loglevel error -show_format -i pipe:'.split()
        result = subprocess_run(command, input=trimmed_asset.essence.read(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
        video_info = json.loads(result.stdout.decode('utf-8'))
        assert bool(video_info.get('format'))

    def test_extract_frame_asset_receives_correct_mime_type(self, processor, video_asset, image_asset):
        image_mime_type = image_asset.mime_type
        extract_frame_operator = processor.extract_frame(mime_type=image_mime_type)

        extracted_asset = extract_frame_operator(video_asset)

        assert extracted_asset.mime_type == image_mime_type

    def test_extract_frame_asset_is_image_with_same_size_as_source(self, processor, video_asset, image_asset):
        image_mime_type = image_asset.mime_type
        extract_frame_operator = processor.extract_frame(mime_type=image_mime_type)

        extracted_asset = extract_frame_operator(video_asset)

        extracted_image = PIL.Image.open(extracted_asset.essence)
        assert extracted_image.width > 0
        assert extracted_image.width == video_asset.width
        assert extracted_image.height > 0
        assert extracted_image.height == video_asset.height

    def test_extract_frame_raises_error_for_unknown_source_format(self, processor, unknown_asset, image_asset):
        image_mime_type = image_asset.mime_type
        extract_frame_operator = processor.extract_frame(mime_type=image_mime_type)

        with pytest.raises(UnsupportedFormatError):
            extract_frame_operator(unknown_asset)

    def test_extract_frame_raises_error_for_unknown_target_format(self, processor, video_asset):
        image_mime_type = 'application/x-unknown'
        extract_frame_operator = processor.extract_frame(mime_type=image_mime_type)

        with pytest.raises(UnsupportedFormatError):
            extract_frame_operator(video_asset)
