import json
import subprocess
from collections import defaultdict

import PIL.Image
import pytest

import madam.video
from madam.core import OperatorError, UnsupportedFormatError
from madam.future import subprocess_run
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_DURATION
from assets import image_asset, jpeg_image_asset, png_image_asset_rgb, png_image_asset_gray, png_image_asset, \
    gif_image_asset, bmp_image_asset, tiff_image_asset, webp_image_asset
from assets import video_asset_with_subtitle, video_asset, avi_video_asset, mp2_video_asset, mp4_video_asset, \
    mkv_video_asset, ogg_video_asset
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
        assert converted_asset.duration == pytest.approx(DEFAULT_DURATION, rel=0.2)

    def test_convert_can_process_all_streams(self, processor, video_asset_with_subtitle):
        conversion_operator = processor.convert(mime_type='video/quicktime',
                                                video=dict(codec='h264', bitrate=50),
                                                audio=dict(codec='aac', bitrate=24),
                                                subtitle=dict(codec='mov_text'))

        converted_asset = conversion_operator(video_asset_with_subtitle)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        subtitle_streams = streams_by_type.get('subtitle', [])
        assert len(video_streams) == 1
        assert video_streams[0]['codec_name'] == 'h264'
        assert len(audio_streams) == 1
        assert audio_streams[0]['codec_name'] == 'aac'
        assert len(subtitle_streams) == 1
        assert subtitle_streams[0]['codec_name'] == 'mov_text'

    def test_convert_can_strip_all_streams_except_subtitle(self, processor, video_asset_with_subtitle):
        conversion_operator = processor.convert(mime_type='text/vtt',
                                                video=dict(codec=None),
                                                audio=dict(codec=None),
                                                subtitle=dict(codec='webvtt'))

        converted_asset = conversion_operator(video_asset_with_subtitle)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        subtitle_streams = streams_by_type.get('subtitle', [])
        assert len(video_streams) == 0
        assert len(audio_streams) == 0
        assert len(subtitle_streams) == 1
        assert subtitle_streams[0]['codec_name'] == 'webvtt'

    def test_convert_can_strip_all_streams_except_video(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='video/x-matroska',
                                                video=dict(codec='h264', bitrate=50),
                                                audio=dict(codec=None),
                                                subtitle=dict(codec=None))

        converted_asset = conversion_operator(video_asset)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        subtitle_streams = streams_by_type.get('subtitle', [])
        assert len(video_streams) == 1
        assert video_streams[0]['codec_name'] == 'h264'
        assert len(audio_streams) == 0
        assert len(subtitle_streams) == 0

    def test_convert_can_strip_all_streams_except_audio(self, processor, video_asset):
        conversion_operator = processor.convert(mime_type='audio/mpeg',
                                                video=dict(codec=None),
                                                audio=dict(codec='mp3', bitrate=32),
                                                subtitle=dict(codec=None))

        converted_asset = conversion_operator(video_asset)

        streams_by_type = self.__probe_streams_by_type(converted_asset)
        video_streams = streams_by_type.get('video', [])
        audio_streams = streams_by_type.get('audio', [])
        subtitle_streams = streams_by_type.get('subtitle', [])
        assert len(video_streams) == 0
        assert len(audio_streams) == 1
        assert audio_streams[0]['codec_name'] == 'mp3'
        assert len(subtitle_streams) == 0

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

    def test_trim_with_negative_seconds_calculates_correct_duration(self, processor, video_asset):
        trim_operator = processor.trim(from_seconds=0.0, to_seconds=-0.1)

        trimmed_asset = trim_operator(video_asset)

        assert trimmed_asset.duration != video_asset.duration
        assert trimmed_asset.duration == video_asset.duration - 0.1

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

    def test_crop_works_only_for_video_assets(self, processor, unknown_asset):
        crop_operator = processor.crop(x=0, y=0, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)

        with pytest.raises(UnsupportedFormatError):
            crop_operator(unknown_asset)

    def test_crop_with_original_dimensions_returns_identical_asset(self, processor, video_asset):
        crop_operator = processor.crop(x=0, y=0, width=video_asset.width, height=video_asset.height)

        cropped_asset = crop_operator(video_asset)

        assert cropped_asset is video_asset

    def test_crop_returns_asset_with_correct_dimensions(self, processor, video_asset):
        crop_width = video_asset.width // 2
        crop_height = video_asset.height // 2
        crop_x = (video_asset.width - crop_width) // 2
        crop_y = (video_asset.height - crop_height) // 2
        crop_operator = processor.crop(x=crop_x, y=crop_y, width=crop_width, height=crop_height)

        cropped_asset = crop_operator(video_asset)

        assert cropped_asset.width == crop_width
        assert cropped_asset.height == crop_height

    @pytest.mark.parametrize('x, y, width, height, cropped_width, cropped_height', [
        (-DEFAULT_WIDTH//2, -DEFAULT_HEIGHT//2, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2),
        (DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2),
    ])
    def test_crop_fixes_partially_overlapping_cropping_area(self, processor, video_asset,
                                                            x, y, width, height, cropped_width, cropped_height):
        crop_operator = processor.crop(x=x, y=y, width=width, height=height)

        cropped_asset = crop_operator(video_asset)

        assert cropped_asset.width == cropped_width
        assert cropped_asset.height == cropped_height

    @pytest.mark.parametrize('x, y, width, height', [
        (-DEFAULT_WIDTH, -DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
        (DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
        (0, 0, -DEFAULT_WIDTH, -DEFAULT_HEIGHT),
    ])
    def test_crop_fails_with_non_overlapping_cropping_area(self, processor, video_asset, x, y, width, height):
        crop_operator = processor.crop(x=x, y=y, width=width, height=height)

        with pytest.raises(OperatorError):
            crop_operator(video_asset)

    def test_rotate_works_only_for_video_assets(self, processor, unknown_asset):
        crop_operator = processor.rotate(angle=45)

        with pytest.raises(UnsupportedFormatError):
            crop_operator(unknown_asset)

    @pytest.mark.parametrize('angle', [0.0, 360.0, -360.0])
    def test_rotate_without_rotation_returns_identical_asset(self, processor, video_asset, angle):
        rotate_operator = processor.rotate(angle=angle)

        rotated_asset = rotate_operator(video_asset)

        assert rotated_asset is video_asset

    @pytest.mark.parametrize('angle', [-45.0, 15.0, 90.0])
    def test_rotate_without_expand_maintains_original_dimensions(self, processor, video_asset, angle):
        rotate_operator = processor.rotate(angle=angle)

        rotated_asset = rotate_operator(video_asset)

        assert rotated_asset.width == video_asset.width
        assert rotated_asset.height == video_asset.height

    @pytest.mark.parametrize('angle', [-45.0, 15.0, 90.0])
    def test_rotate_with_expand_changes_dimensions(self, processor, video_asset, angle):
        rotate_operator = processor.rotate(angle=angle, expand=True)

        rotated_asset = rotate_operator(video_asset)

        assert rotated_asset.width != video_asset.width
        assert rotated_asset.height != video_asset.height
