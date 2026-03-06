import io
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from math import ceil, cos, isfinite, pi, radians, sin
from types import TracebackType
from typing import IO, Any, Self

import PIL.Image
from bidict import bidict

from madam.core import (
    Asset,
    MetadataProcessor,
    OperatorError,
    ProcessingContext,
    Processor,
    UnsupportedFormatError,
    operator,
)
from madam.mime import MimeType
from madam.streaming import MultiFileOutput


class FFmpegFilterGraph:
    """
    Accumulates FFmpeg video and audio filters for a single deferred pipeline run.

    An :class:`FFmpegFilterGraph` is created automatically by
    :class:`FFmpegProcessor` when a group of consecutive FFmpeg operators is
    gathered by :class:`~madam.core.Pipeline` for deferred execution.  Custom
    operator implementations can also receive one via :attr:`FFmpegContext.graph`
    and call its mutation methods.

    Mutation interface — call these from operator implementations:

    * :meth:`add_video_filter` — append a video filter (e.g. ``scale``, ``crop``).
    * :meth:`add_audio_filter` — append an audio filter (e.g. ``volume``, ``atrim``).
    * :meth:`set_output_format` — set the target MIME type for the encoded output.
    * :meth:`set_codec_options` — merge codec/muxer options; raises on conflict.

    Read-only views — inspect after accumulation:

    * :attr:`video_filter_string` — comma-joined ``-vf`` filter string.
    * :attr:`audio_filter_string` — comma-joined ``-af`` filter string.

    :ivar output_mime_type: MIME type string set by :meth:`set_output_format`,
        or ``None`` if not yet set.
    :vartype output_mime_type: str | None
    :ivar codec_options: Codec and muxer options accumulated by
        :meth:`set_codec_options`.  Keys are ``ffmpeg`` option names (e.g.
        ``'vcodec'``, ``'acodec'``); values are their settings.
    :vartype codec_options: dict[str, Any]
    :ivar extra_input_args: Additional raw ``ffmpeg`` CLI arguments inserted
        immediately *before* the ``-i <input>`` flag.  Use for input-side options
        such as ``['-ss', '00:00:10']`` to seek before decoding.
    :vartype extra_input_args: list[str]
    :ivar extra_output_args: Additional raw ``ffmpeg`` CLI arguments inserted
        immediately *after* the ``-i <input>`` flag, before filter and codec
        flags.  Use for output-side options that are not expressible as filters,
        such as ``['-t', '30']`` to limit duration.
    :vartype extra_output_args: list[str]

    .. versionadded:: 1.0
    """

    def __init__(self) -> None:
        self._video_filters: list[str] = []
        self._audio_filters: list[str] = []
        self.output_mime_type: str | None = None
        self.codec_options: dict[str, Any] = {}
        self.extra_input_args: list[str] = []
        self.extra_output_args: list[str] = []

    # ------------------------------------------------------------------
    # Filter accumulation
    # ------------------------------------------------------------------

    @staticmethod
    def _format_filter(name: str, **params: Any) -> str:
        if not params:
            return name
        param_str = ':'.join(f'{k}={v}' for k, v in params.items())
        return f'{name}={param_str}'

    def add_video_filter(self, name: str, **params: Any) -> None:
        """Append a video filter (e.g. ``scale``, ``crop``) to the chain."""
        self._video_filters.append(self._format_filter(name, **params))

    def add_audio_filter(self, name: str, **params: Any) -> None:
        """Append an audio filter (e.g. ``volume``, ``atrim``) to the chain."""
        self._audio_filters.append(self._format_filter(name, **params))

    # ------------------------------------------------------------------
    # Output configuration
    # ------------------------------------------------------------------

    def set_output_format(self, mime_type: str) -> None:
        """Set the target output MIME type for this run."""
        self.output_mime_type = str(mime_type)

    def set_codec_options(self, **opts: Any) -> None:
        """
        Merge codec options into the accumulated options dict.

        :raises ValueError: if the same key already has a different value.
        """
        for key, value in opts.items():
            if key in self.codec_options and self.codec_options[key] != value:
                raise ValueError(
                    f'Conflicting codec option {key!r}: '
                    f'{self.codec_options[key]!r} vs {value!r}'
                )
            self.codec_options[key] = value

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def video_filter_string(self) -> str:
        """Comma-joined FFmpeg ``-vf`` filter string, or empty string."""
        return ','.join(self._video_filters)

    @property
    def audio_filter_string(self) -> str:
        """Comma-joined FFmpeg ``-af`` filter string, or empty string."""
        return ','.join(self._audio_filters)


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a ``'N.N.N'`` version string into a comparable tuple of ints."""
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', version_str)
    if not match:
        raise ValueError(f'Cannot parse version string: {version_str!r}')
    return tuple(int(g) for g in match.groups() if g is not None)


def _ffmpeg_error_message(error: subprocess.CalledProcessError, operation: str) -> str:
    """Return a concise, backend-agnostic error message from a failed FFmpeg call.

    Extracts only the last non-empty line from FFmpeg stderr so that internal
    codec names, filter-graph syntax, and file paths are not exposed verbatim.
    """
    stderr = error.stderr.decode('utf-8', errors='replace') if error.stderr else ''
    last_line = next(
        (line.strip() for line in reversed(stderr.splitlines()) if line.strip()),
        'unknown error',
    )
    return f'Could not {operation}: {last_line}'


def _probe(file: IO) -> Any:
    """Run ffprobe on *file* and return the parsed JSON.

    Data is sent via stdin (``pipe:0``) to avoid a temp-file copy.  A small
    number of container formats require a seekable input to report duration;
    for those, a NamedTemporaryFile fallback is used automatically when the
    stdin probe omits ``format.duration``.
    """
    data = file.read()
    file.seek(0)
    base_command: list[str] = [
        'ffprobe',
        '-loglevel',
        'error',
        '-print_format',
        'json',
        '-show_format',
        '-show_streams',
    ]
    # Fast path: pipe data via stdin.
    result = subprocess.run(base_command + ['pipe:0'], input=data, capture_output=True, check=True)
    probe_data = json.loads(result.stdout.decode('utf-8'))

    # Fallback: some raw/headerless formats (AAC ADTS, raw MP2, NUT …) need a
    # seekable source to report duration.  Re-probe via a named temp file.
    if 'duration' not in probe_data.get('format', {}):
        with tempfile.NamedTemporaryFile(mode='wb', suffix='_probe') as tmp:
            tmp.write(data)
            tmp.flush()
            result = subprocess.run(base_command + [tmp.name], capture_output=True, check=True)
        probe_data = json.loads(result.stdout.decode('utf-8'))

    return probe_data


def _combine_metadata(asset, *cloned_keys: str, **additional_metadata: Any) -> dict[str, Any]:
    metadata = {key: asset.metadata[key] for key in cloned_keys if key in asset.metadata}
    metadata.update(additional_metadata)
    return metadata


def _get_decoder_and_stream_type(probe_data: Mapping[str, Any]) -> tuple[str, str]:
    decoder_name = probe_data['format']['format_name']

    stream_types = {stream['codec_type'] for stream in probe_data['streams']}
    if 'video' in stream_types:
        stream_type = 'video'
    elif 'audio' in stream_types:
        stream_type = 'audio'
    elif 'subtitle' in stream_types:
        stream_type = 'subtitle'
    else:
        stream_type = ''

    return decoder_name, stream_type


def _param_map_to_seq(param_mapping: Mapping[str, Any]) -> list[str]:
    params = []
    for param, value in param_mapping.items():
        params.append(f'-{param}')
        if value is not None:
            params.append(str(value))
    return params


def _run_ffmpeg_with_progress(command: list[str], progress_callback: Callable[[dict[str, str]], None]) -> None:
    """
    Run an FFmpeg *command* and call *progress_callback* with a parsed
    progress dict after each FFmpeg progress block.

    FFmpeg is invoked with ``-progress pipe:1`` so structured key=value
    progress lines are written to stdout.  Each completed block (terminated
    by a ``progress=continue`` or ``progress=end`` line) is delivered to the
    callback as a ``dict[str, str]``.

    :param command: FFmpeg command list (must not already contain -progress).
    :param progress_callback: Callable invoked with each progress snapshot.
    :raises OperatorError: on non-zero FFmpeg exit.
    """
    progress_command = list(command)
    # Insert -progress pipe:1 right after 'ffmpeg' and before output flags.
    # We write progress to stdout; stderr carries error messages.
    try:
        out_flag_idx = progress_command.index('-y')
    except ValueError:
        out_flag_idx = len(progress_command) - 1
    progress_command[out_flag_idx:out_flag_idx] = ['-progress', 'pipe:1']

    with subprocess.Popen(
        progress_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        current_block: dict[str, str] = {}
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.decode('utf-8', errors='replace').strip()
            if '=' in line:
                key, _, value = line.partition('=')
                current_block[key.strip()] = value.strip()
            if line.startswith('progress='):
                if current_block:
                    progress_callback(dict(current_block))
                current_block = {}
        proc.wait()
        if proc.returncode != 0:
            assert proc.stderr is not None
            stderr_bytes = proc.stderr.read()
            stderr_text = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ''
            last_line = next(
                (line.strip() for line in reversed(stderr_text.splitlines()) if line.strip()),
                'unknown error',
            )
            raise OperatorError(f'Could not run FFmpeg: {last_line}')


class _FFmpegContext(tempfile.TemporaryDirectory[str]):
    def __init__(self, source: IO, result: IO) -> None:
        super().__init__(prefix='madam')
        self.__source = source
        self.__result = result

    def __enter__(self) -> Self:  # type: ignore[override]
        tmpdir_path = super().__enter__()
        self.input_path = os.path.join(tmpdir_path, 'input_file')
        self.output_path = os.path.join(tmpdir_path, 'output_file')

        with open(self.input_path, 'wb') as temp_in:
            shutil.copyfileobj(self.__source, temp_in)
            self.__source.seek(0)

        return self

    def __exit__(  # type: ignore[override]
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        if os.path.exists(self.output_path):
            with open(self.output_path, 'rb') as temp_out:
                shutil.copyfileobj(temp_out, self.__result)
                self.__result.seek(0)

        super().__exit__(exc_type, exc_val, exc_tb)


class VideoCodec:
    """Named constants for video codec strings accepted by :meth:`FFmpegProcessor.convert`.

    Use these instead of raw FFmpeg codec names to avoid depending on FFmpeg internals::

        processor.convert(mime_type='video/mp4', video={'codec': VideoCodec.H264})

    .. versionadded:: 0.23
    """

    H264 = 'libx264'
    H265 = 'libx265'
    VP8 = 'libvpx'
    VP9 = 'libvpx-vp9'
    AV1 = 'libaom-av1'
    COPY = 'copy'
    NONE = None  # discard video stream (-vn)


class AudioCodec:
    """Named constants for audio codec strings accepted by :meth:`FFmpegProcessor.convert`.

    Use these instead of raw FFmpeg codec names to avoid depending on FFmpeg internals::

        processor.convert(mime_type='audio/mpeg', audio={'codec': AudioCodec.MP3})

    .. versionadded:: 0.23
    """

    AAC = 'aac'
    OPUS = 'libopus'
    VORBIS = 'libvorbis'
    MP3 = 'libmp3lame'
    FLAC = 'flac'
    COPY = 'copy'
    NONE = None  # discard audio stream (-an)


class FFmpegContext(ProcessingContext):
    """
    Deferred in-memory state for an FFmpeg processing run.

    Holds the original input :class:`~madam.core.Asset` and an
    :class:`FFmpegFilterGraph` that accumulates the filter chain built up by
    consecutive :class:`FFmpegProcessor` operators.  Call :meth:`materialize`
    to execute a single ``ffmpeg`` subprocess that applies all accumulated
    filters at once.

    Instances are created by :class:`FFmpegProcessor` and passed to
    :meth:`~madam.core.Processor.execute_run`.  Custom operator
    implementations can inspect or extend the accumulated state before
    materialisation.

    :ivar asset: The original input asset whose essence will be passed as the
        ``ffmpeg`` input file.  Do not replace this attribute; append filters
        to :attr:`graph` instead.
    :vartype asset: Asset
    :ivar graph: The filter graph being built up for this run.  Append
        additional filters or set codec options by calling the mutation
        methods on this object.
    :vartype graph: FFmpegFilterGraph

    .. versionadded:: 1.0
    """

    def __init__(self, processor: 'FFmpegProcessor', asset: Asset, graph: FFmpegFilterGraph) -> None:
        self._proc = processor
        self.asset = asset
        self.graph = graph

    @property
    def processor(self) -> 'FFmpegProcessor':
        return self._proc

    def materialize(self) -> Asset:
        """Run one ``ffmpeg`` subprocess from the accumulated filter graph."""
        return self._proc._materialize_context(self)


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.

    The minimum version of FFmpeg required is v3.3.
    """

    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): MimeType('video/x-matroska'),
        ('matroska,webm', 'audio'): MimeType('audio/webm'),
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): MimeType('video/quicktime'),
        ('avi', 'video'): MimeType('video/x-msvideo'),
        ('mpegts', 'video'): MimeType('video/mp2t'),
        ('nut', 'video'): MimeType('video/x-nut'),
        ('ogg', 'video'): MimeType('video/ogg'),
        ('aac', 'audio'): MimeType('audio/aac'),
        ('flac', 'audio'): MimeType('audio/flac'),
        ('mp3', 'audio'): MimeType('audio/mpeg'),
        ('nut', 'audio'): MimeType('audio/x-nut'),
        ('ogg', 'audio'): MimeType('audio/ogg'),
        ('wav', 'audio'): MimeType('audio/wav'),
        ('webvtt', 'subtitle'): MimeType('text/vtt'),
    }

    __mime_type_to_encoder = {
        MimeType('video/mp4'): 'mp4',
        MimeType('video/webm'): 'webm',
        MimeType('video/x-matroska'): 'matroska',
        MimeType('video/quicktime'): 'mov',
        MimeType('video/x-msvideo'): 'avi',
        MimeType('video/mp2t'): 'mpegts',
        MimeType('video/x-nut'): 'nut',
        MimeType('video/ogg'): 'ogg',
        MimeType('audio/aac'): 'adts',
        MimeType('audio/flac'): 'flac',
        MimeType('audio/mpeg'): 'mp3',
        MimeType('audio/opus'): 'opus',
        MimeType('audio/webm'): 'webm',
        MimeType('audio/x-nut'): 'nut',
        MimeType('audio/ogg'): 'ogg',
        MimeType('audio/wav'): 'wav',
        MimeType('image/bmp'): 'image2',
        MimeType('image/gif'): 'gif',
        MimeType('image/jpeg'): 'image2',
        MimeType('image/png'): 'image2',
        MimeType('image/tiff'): 'image2',
        MimeType('image/webp'): 'image2',
        MimeType('text/vnd.dvb.subtitle'): 'dvbsub',
        MimeType('text/vtt'): 'webvtt',
    }

    __mime_type_to_codec = {
        MimeType('image/bmp'): 'bmp',
        MimeType('image/gif'): 'gif',
        MimeType('image/jpeg'): 'mjpeg',
        MimeType('image/png'): 'png',
        MimeType('image/tiff'): 'tiff',
        MimeType('image/webp'): 'libwebp',
    }

    __codec_options = {
        'video': {
            'libx264': {
                'preset': 'slow',
                'crf': 23,
            },
            'libx265': {
                'preset': 'slow',
                'crf': 28,
            },
            'libvpx': {
                'crf': 10,
            },
            'libvpx-vp9': {
                'row-mt': 1,
                'crf': 32,
            },
            'opus': {'strict': -2},
            'vorbis': {'ac': 2, 'strict': -2},
            'vp9': {
                'tile-columns': 6,
                'crf': 32,
            },
        }
    }

    __container_options = {
        MimeType('video/x-matroska'): [
            '-avoid_negative_ts',
            'make_zero',
        ],
    }

    __ffmpeg_pix_fmt_to_color_mode = {
        # Luminance
        'gray': ('LUMA', 8, 'uint'),
        'gray9be': ('LUMA', 9, 'uint'),
        'gray9le': ('LUMA', 9, 'uint'),
        'gray10be': ('LUMA', 10, 'uint'),
        'gray10le': ('LUMA', 10, 'uint'),
        'gray12be': ('LUMA', 12, 'uint'),
        'gray12le': ('LUMA', 12, 'uint'),
        'gray16be': ('LUMA', 16, 'uint'),
        'gray16le': ('LUMA', 16, 'uint'),
        # Luminance, alpha
        'monob': ('LUMA', 1, 'uint'),
        'monow': ('LUMA', 1, 'uint'),
        'ya8': ('LUMAA', 8, 'uint'),
        'ya16be': ('LUMAA', 16, 'uint'),
        'ya16le': ('LUMAA', 16, 'uint'),
        # Palette
        'pal8': ('PALETTE', 8, 'uint'),
        # Red, green, blue
        'bayer_bggr8': ('RGB', 8, 'uint'),
        'bayer_bggr16be': ('RGB', 16, 'uint'),
        'bayer_bggr16le': ('RGB', 16, 'uint'),
        'bayer_gbrg8': ('RGB', 8, 'uint'),
        'bayer_gbrg16be': ('RGB', 16, 'uint'),
        'bayer_gbrg16le': ('RGB', 16, 'uint'),
        'bayer_grbg8': ('RGB', 8, 'uint'),
        'bayer_grbg16be': ('RGB', 16, 'uint'),
        'bayer_grbg16le': ('RGB', 16, 'uint'),
        'bayer_rggb8': ('RGB', 8, 'uint'),
        'bayer_rggb16be': ('RGB', 16, 'uint'),
        'bayer_rggb16le': ('RGB', 16, 'uint'),
        'bgr4': ('RGB', 8, 'uint'),
        'bgr4_byte': ('RGB', 8, 'uint'),
        'bgr24': ('RGB', 8, 'uint'),
        'bgr48be': ('RGB', 16, 'uint'),
        'bgr48le': ('RGB', 16, 'uint'),
        'bgr444be': ('RGB', 8, 'uint'),
        'bgr444le': ('RGB', 8, 'uint'),
        'bgr555be': ('RGB', 8, 'uint'),
        'bgr555le': ('RGB', 8, 'uint'),
        'bgr565be': ('RGB', 8, 'uint'),
        'bgr565le': ('RGB', 8, 'uint'),
        'bgr8': ('RGB', 8, 'uint'),
        'gbrp': ('RGB', 8, 'uint'),
        'gbrp9be': ('RGB', 9, 'uint'),
        'gbrp9le': ('RGB', 9, 'uint'),
        'gbrp10be': ('RGB', 10, 'uint'),
        'gbrp10le': ('RGB', 10, 'uint'),
        'gbrp12be': ('RGB', 12, 'uint'),
        'gbrp12le': ('RGB', 12, 'uint'),
        'gbrp14be': ('RGB', 14, 'uint'),
        'gbrp14le': ('RGB', 14, 'uint'),
        'gbrp16be': ('RGB', 16, 'uint'),
        'gbrp16le': ('RGB', 16, 'uint'),
        'gbrpf32be': ('RGB', 32, 'float'),
        'gbrpf32le': ('RGB', 32, 'float'),
        'rgb4': ('RGB', 8, 'uint'),
        'rgb4_byte': ('RGB', 8, 'uint'),
        'rgb24': ('RGB', 8, 'uint'),
        'rgb48be': ('RGB', 16, 'uint'),
        'rgb48le': ('RGB', 16, 'uint'),
        'rgb444be': ('RGB', 8, 'uint'),
        'rgb444le': ('RGB', 8, 'uint'),
        'rgb555be': ('RGB', 8, 'uint'),
        'rgb555le': ('RGB', 8, 'uint'),
        'rgb565be': ('RGB', 8, 'uint'),
        'rgb565le': ('RGB', 8, 'uint'),
        'rgb8': ('RGB', 8, 'uint'),
        # Red, green, blue, alpha
        'abgr': ('RGBA', 8, 'uint'),
        'argb': ('RGBA', 8, 'uint'),
        'bgra': ('RGBA', 8, 'uint'),
        'bgra64be': ('RGBA', 16, 'uint'),
        'bgra64le': ('RGBA', 16, 'uint'),
        'gbrap': ('RGBA', 8, 'uint'),
        'gbrap10be': ('RGBA', 16, 'uint'),
        'gbrap10le': ('RGBA', 16, 'uint'),
        'gbrap12be': ('RGBA', 16, 'uint'),
        'gbrap12le': ('RGBA', 16, 'uint'),
        'gbrap16be': ('RGBA', 16, 'uint'),
        'gbrap16le': ('RGBA', 16, 'uint'),
        'gbrapf32be': ('RGBA', 32, 'float'),
        'gbrapf32le': ('RGBA', 32, 'float'),
        'rgba': ('RGBA', 8, 'uint'),
        'rgba64be': ('RGBA', 16, 'uint'),
        'rgba64le': ('RGBA', 16, 'uint'),
        # Red, green, blue, padding
        '0bgr': ('RGBX', 8, 'uint'),
        '0rgb': ('RGBX', 8, 'uint'),
        'bgr0': ('RGBX', 8, 'uint'),
        'rgb0': ('RGBX', 8, 'uint'),
        # X, Y, Z
        'xyz12be': ('XYZ', 12, 'uint'),
        'xyz12le': ('XYZ', 12, 'uint'),
        # Luminance, blue-difference chrominance, red-difference chrominance
        'nv12': ('YUV', 8, 'uint'),
        'nv16': ('YUV', 8, 'uint'),
        'nv20be': ('YUV', 8, 'uint'),
        'nv20le': ('YUV', 8, 'uint'),
        'nv21': ('YUV', 8, 'uint'),
        'p010be': ('YUV', 10, 'uint'),
        'p010le': ('YUV', 10, 'uint'),
        'p016be': ('YUV', 16, 'uint'),
        'p016le': ('YUV', 16, 'uint'),
        'uyvy422': ('YUV', 8, 'uint'),
        'uyyvyy411': ('YUV', 8, 'uint'),
        'yuv410p': ('YUV', 8, 'uint'),
        'yuv411p': ('YUV', 8, 'uint'),
        'yuv420p': ('YUV', 8, 'uint'),
        'yuv420p9be': ('YUV', 9, 'uint'),
        'yuv420p9le': ('YUV', 9, 'uint'),
        'yuv420p10be': ('YUV', 10, 'uint'),
        'yuv420p10le': ('YUV', 10, 'uint'),
        'yuv420p12be': ('YUV', 12, 'uint'),
        'yuv420p12le': ('YUV', 12, 'uint'),
        'yuv420p14be': ('YUV', 14, 'uint'),
        'yuv420p14le': ('YUV', 14, 'uint'),
        'yuv420p16be': ('YUV', 16, 'uint'),
        'yuv420p16le': ('YUV', 16, 'uint'),
        'yuv422p': ('YUV', 8, 'uint'),
        'yuv422p9be': ('YUV', 9, 'uint'),
        'yuv422p9le': ('YUV', 9, 'uint'),
        'yuv422p10be': ('YUV', 10, 'uint'),
        'yuv422p10le': ('YUV', 10, 'uint'),
        'yuv422p12be': ('YUV', 12, 'uint'),
        'yuv422p12le': ('YUV', 12, 'uint'),
        'yuv422p14be': ('YUV', 14, 'uint'),
        'yuv422p14le': ('YUV', 14, 'uint'),
        'yuv422p16be': ('YUV', 16, 'uint'),
        'yuv422p16le': ('YUV', 16, 'uint'),
        'yuv440p': ('YUV', 8, 'uint'),
        'yuv440p10be': ('YUV', 10, 'uint'),
        'yuv440p10le': ('YUV', 10, 'uint'),
        'yuv440p12be': ('YUV', 12, 'uint'),
        'yuv440p12le': ('YUV', 12, 'uint'),
        'yuv444p': ('YUV', 8, 'uint'),
        'yuv444p9be': ('YUV', 9, 'uint'),
        'yuv444p9le': ('YUV', 9, 'uint'),
        'yuv444p10be': ('YUV', 10, 'uint'),
        'yuv444p10le': ('YUV', 10, 'uint'),
        'yuv444p12be': ('YUV', 12, 'uint'),
        'yuv444p12le': ('YUV', 12, 'uint'),
        'yuv444p14be': ('YUV', 14, 'uint'),
        'yuv444p14le': ('YUV', 14, 'uint'),
        'yuv444p16be': ('YUV', 16, 'uint'),
        'yuv444p16le': ('YUV', 16, 'uint'),
        'yuvj411p': ('YUV', 8, 'uint'),
        'yuvj420p': ('YUV', 8, 'uint'),
        'yuvj422p': ('YUV', 8, 'uint'),
        'yuvj440p': ('YUV', 8, 'uint'),
        'yuvj444p': ('YUV', 8, 'uint'),
        'yuyv422': ('YUV', 8, 'uint'),
        'yvyu422': ('YUV', 8, 'uint'),
        # Luminance, blue-difference chrominance, red-difference chrominance, alpha
        'ayuv64be': ('YUVA', 16, 'uint'),
        'ayuv64le': ('YUVA', 16, 'uint'),
        'yuva420p': ('YUVA', 8, 'uint'),
        'yuva420p9be': ('YUVA', 9, 'uint'),
        'yuva420p9le': ('YUVA', 9, 'uint'),
        'yuva420p10be': ('YUVA', 10, 'uint'),
        'yuva420p10le': ('YUVA', 10, 'uint'),
        'yuva420p16be': ('YUVA', 16, 'uint'),
        'yuva420p16le': ('YUVA', 16, 'uint'),
        'yuva422p': ('YUVA', 8, 'uint'),
        'yuva422p9be': ('YUVA', 9, 'uint'),
        'yuva422p9le': ('YUVA', 9, 'uint'),
        'yuva422p10be': ('YUVA', 10, 'uint'),
        'yuva422p10le': ('YUVA', 10, 'uint'),
        'yuva422p16be': ('YUVA', 16, 'uint'),
        'yuva422p16le': ('YUVA', 16, 'uint'),
        'yuva444p': ('YUVA', 8, 'uint'),
        'yuva444p9be': ('YUVA', 9, 'uint'),
        'yuva444p9le': ('YUVA', 9, 'uint'),
        'yuva444p10be': ('YUVA', 10, 'uint'),
        'yuva444p10le': ('YUVA', 10, 'uint'),
        'yuva444p16be': ('YUVA', 16, 'uint'),
        'yuva444p16le': ('YUVA', 16, 'uint'),
    }

    __color_mode_to_ffmpeg_pix_fmt = {
        ('LUMA', 1, 'uint'): 'monob',
        ('LUMA', 8, 'uint'): 'gray',
        ('LUMA', 9, 'uint'): 'gray9le',
        ('LUMA', 10, 'uint'): 'gray10le',
        ('LUMA', 12, 'uint'): 'gray12le',
        ('LUMA', 16, 'uint'): 'gray16le',
        ('LUMAA', 8, 'uint'): 'ya8',
        ('LUMAA', 16, 'uint'): 'ya16le',
        ('PALETTE', 8, 'uint'): 'pal8',
        ('RGB', 8, 'uint'): 'rgb24',
        ('RGB', 9, 'uint'): 'gbrp9le',
        ('RGB', 10, 'uint'): 'gbrp10le',
        ('RGB', 12, 'uint'): 'gbrp12le',
        ('RGB', 16, 'uint'): 'rgb48le',
        ('RGB', 32, 'float'): 'gbrpf32le',
        ('RGBA', 8, 'uint'): 'rgba',
        ('RGBA', 16, 'uint'): 'rgba64le',
        ('RGBA', 32, 'float'): 'gbrapf32le',
        ('RGBX', 8, 'uint'): 'rgb0',
        ('XYZ', 12, 'uint'): 'xyz12le',
        ('YUV', 8, 'uint'): 'yuv420p',
        ('YUV', 9, 'uint'): 'yuv420p9le',
        ('YUV', 10, 'uint'): 'yuv420p10le',
        ('YUV', 12, 'uint'): 'yuv420p12le',
        ('YUV', 14, 'uint'): 'yuv420p14le',
        ('YUV', 16, 'uint'): 'yuv420p16le',
        ('YUVA', 8, 'uint'): 'yuva420p',
        ('YUVA', 9, 'uint'): 'yuva420p9le',
        ('YUVA', 10, 'uint'): 'yuva420p10le',
        ('YUVA', 16, 'uint'): 'yuva420p16le',
    }

    _MIN_VERSION: tuple[int, ...] = (3, 3)

    @property
    def supported_mime_types(self) -> frozenset:
        return frozenset(FFmpegProcessor.__decoder_and_stream_type_to_mime_type.values())

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `FFmpegProcessor`.

        :param config: Mapping with settings.
        :raises EnvironmentError: if ffprobe is not found, times out, or its
            version is below the minimum requirement (3.3).
        """
        super().__init__(config)

        try:
            result = subprocess.run(
                ['ffprobe', '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except FileNotFoundError:
            raise EnvironmentError('ffprobe not found. Install FFmpeg >= 3.3 and ensure it is on PATH.')
        except subprocess.TimeoutExpired:
            raise EnvironmentError('ffprobe version check timed out.')

        parts = result.stdout.decode('utf-8').split()
        try:
            version_idx = parts.index('version') + 1
            version_string = parts[version_idx]
        except (ValueError, IndexError):
            raise EnvironmentError('Cannot determine ffprobe version from output.')

        detected = _parse_version(version_string)
        if detected < self._MIN_VERSION:
            min_str = '.'.join(str(v) for v in self._MIN_VERSION)
            raise EnvironmentError(f'Found ffprobe version {version_string}. Requiring at least version {min_str}.')

        self._configured_threads: int = self.config.get('ffmpeg', {}).get('threads', 0)

    @property
    def _threads(self) -> int:
        """Resolved thread count, evaluated fresh each call to respect container CPU limits."""
        return self._configured_threads if self._configured_threads > 0 else multiprocessing.cpu_count()

    # ------------------------------------------------------------------
    # Deferred execution support
    # ------------------------------------------------------------------

    def execute_run(self, steps: list[Callable], asset_or_context: 'Asset | FFmpegContext') -> 'Asset | FFmpegContext':  # type: ignore[override]
        """
        Group consecutive FFmpegProcessor operators into a single subprocess.

        Each step's ``_accumulate_*`` method appends to the
        :class:`FFmpegFilterGraph`.  Operators without an accumulation method
        fall back to direct sequential execution (which may spawn a subprocess).
        The accumulated context is returned for the pipeline to materialise at
        the next processor boundary or pipeline end.
        """
        if isinstance(asset_or_context, FFmpegContext):
            graph = asset_or_context.graph
            asset = asset_or_context.asset
        else:
            asset = asset_or_context
            graph = FFmpegFilterGraph()
            graph.set_output_format(str(asset.mime_type))

        for step in steps:
            op_name = getattr(getattr(step, 'func', None), '__name__', None)
            accumulate = getattr(self, f'_accumulate_{op_name}', None) if op_name else None
            if accumulate is not None:
                asset = accumulate(graph, asset, **step.keywords)  # type: ignore[attr-defined]
            else:
                # Fallback: materialise current context, apply step directly.
                if isinstance(asset_or_context, FFmpegContext):
                    ctx = FFmpegContext(self, asset, graph)
                    asset = ctx.materialize()
                    graph = FFmpegFilterGraph()
                    graph.set_output_format(str(asset.mime_type))
                asset = step(asset)

        return FFmpegContext(self, asset, graph)

    def _materialize_context(self, ctx: 'FFmpegContext') -> Asset:
        """
        Execute a single ``ffmpeg`` subprocess from an accumulated
        :class:`FFmpegFilterGraph` and return the resulting :class:`Asset`.
        """
        asset = ctx.asset
        graph = ctx.graph
        mime_type = MimeType(graph.output_mime_type or str(asset.mime_type))
        encoder_name = self._FFmpegProcessor__mime_type_to_encoder.get(mime_type)  # type: ignore[attr-defined]
        if not encoder_name:
            raise UnsupportedFormatError(f'Unsupported output format: {mime_type}')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ffctx:
            command = ['ffmpeg', '-loglevel', 'error']
            command += graph.extra_input_args
            command += ['-i', ffctx.input_path]
            command += graph.extra_output_args

            vf = graph.video_filter_string
            af = graph.audio_filter_string
            if vf:
                command += ['-filter:v', vf]
            if af:
                command += ['-filter:a', af]

            for key, val in graph.codec_options.items():
                command += [f'-{key}', str(val)]

            command += ['-threads', str(self._threads), '-f', encoder_name, '-y', ffctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as err:
                raise OperatorError(_ffmpeg_error_message(err, 'deferred ffmpeg run'))

        # Re-probe to get accurate metadata for the encoded result.
        result.seek(0)
        return self.read(result)

    def _accumulate_resize(
        self,
        graph: FFmpegFilterGraph,
        asset: Asset,
        *,
        width: int,
        height: int,
    ) -> Asset:
        """Accumulate an FFmpeg scale filter for the resize operator."""
        mime_type = MimeType(asset.mime_type)
        if mime_type.type not in ('image', 'video'):
            raise OperatorError(f'Cannot resize asset of type {mime_type}')
        if width < 1 or height < 1:
            raise ValueError(f'Invalid dimensions: {width:d}x{height:d}')
        graph.add_video_filter('scale', w=width, h=height)
        # Return an updated "virtual" asset with new dimensions for subsequent operators.
        metadata = dict(asset.metadata)
        metadata['width'] = width
        metadata['height'] = height
        return Asset(asset.essence, **metadata)

    def _accumulate_crop(
        self,
        graph: FFmpegFilterGraph,
        asset: Asset,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> Asset:
        """Accumulate an FFmpeg crop filter for the crop operator."""
        mime_type = MimeType(asset.mime_type)
        if mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        max_x = max(0, min(asset.width or width, width + x))
        max_y = max(0, min(asset.height or height, height + y))
        min_x = max(0, min(asset.width or width, x))
        min_y = max(0, min(asset.height or height, y))
        actual_w = max_x - min_x
        actual_h = max_y - min_y

        graph.add_video_filter('crop', w=actual_w, h=actual_h, x=min_x, y=min_y)
        metadata = dict(asset.metadata)
        metadata['width'] = actual_w
        metadata['height'] = actual_h
        return Asset(asset.essence, **metadata)

    def can_read(self, file: IO) -> bool:
        try:
            probe_data = _probe(file)
            decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
            mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
            return bool(mime_type)
        except subprocess.CalledProcessError:
            return False

    def read(self, file: IO) -> Asset:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        metadata: dict[str, Any] = dict(
            mime_type=str(mime_type),
        )

        if 'duration' in probe_data['format']:
            metadata['duration'] = float(probe_data['format']['duration'])

        for stream in probe_data['streams']:
            stream_type = stream.get('codec_type')
            if stream_type in {'video', 'audio', 'subtitle'}:
                # Only use first stream
                if stream_type in metadata:
                    break
                metadata[stream_type] = {}
            if 'width' in stream:
                metadata['width'] = max(stream['width'], metadata.get('width', 0))
            if 'height' in stream:
                metadata['height'] = max(stream['height'], metadata.get('height', 0))
            if stream_type not in metadata:
                continue
            if 'codec_name' in stream:
                metadata[stream_type]['codec'] = stream['codec_name']
            if 'bit_rate' in stream:
                metadata[stream_type]['bitrate'] = float(stream['bit_rate']) / 1000.0
            if 'pix_fmt' in stream:
                color_space, depth, data_type = FFmpegProcessor.__ffmpeg_pix_fmt_to_color_mode[stream['pix_fmt']]
                metadata[stream_type]['color_space'] = color_space
                metadata[stream_type]['depth'] = depth
                metadata[stream_type]['data_type'] = data_type

        return Asset(essence=file, **metadata)

    @operator
    def resize(self, asset: Asset, width: int, height: int) -> Asset:
        """
        Creates a new image or video asset of the specified width and height
        from the essence of the specified image or video asset.

        Width and height must be positive numbers.

        :param asset: Video asset that will serve as the source for the frame
        :type asset: Asset
        :param width: Width of the resized asset
        :type width: int
        :param height: Height of the resized asset
        :type height: int
        :return: New asset with specified width and height
        :rtype: Asset
        """
        if width < 1 or height < 1:
            raise ValueError(f'Invalid dimensions: {width:d}x{height:d}')

        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name:
            raise UnsupportedFormatError(f'Unsupported asset type: {mime_type}')
        if mime_type.type not in ('image', 'video'):
            raise OperatorError(f'Cannot resize asset of type {mime_type}')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = [
                'ffmpeg',
                '-loglevel',
                'error',
                '-f',
                encoder_name,
                '-i',
                ctx.input_path,
                '-filter:v',
                f'scale={width:d}:{height:d}',
                '-qscale',
                '0',
                '-threads',
                str(self._threads),
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'resize asset'))

        metadata = _combine_metadata(
            asset, 'mime_type', 'duration', 'video', 'audio', 'subtitle', width=width, height=height
        )

        return Asset(essence=result, **metadata)

    @operator
    def convert(
        self,
        asset: Asset,
        mime_type: MimeType | str,
        video: Mapping[str, Any] | None = None,
        audio: Mapping[str, Any] | None = None,
        subtitle: Mapping[str, Any] | None = None,
        progress_callback: Callable[[dict[str, str]], None] | None = None,
    ) -> Asset:
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        Additional options can be specified for video, audio, and subtitle streams.
        Options are passed as dictionary instances and can contain various keys for
        each stream type.

        **Options for video streams:**

        - **codec** – Processor-specific name of the video codec as string
        - **bitrate** – Target bitrate in kBit/s as float number

        **Options for audio streams:**

        - **codec** – Processor-specific name of the audio codec as string
        - **bitrate** – Target bitrate in kBit/s as float number

        **Options for subtitle streams:**

        - **codec** – Processor-specific name of the subtitle format as string

        :param asset: Asset whose contents will be converted
        :type asset: Asset
        :param mime_type: MIME type of the video container
        :type mime_type: MimeType or str
        :param video: Dictionary with options for video streams.
        :type video: dict or None
        :param audio: Dictionary with options for audio streams.
        :type audio: dict or None
        :param subtitle: Dictionary with the options for subtitle streams.
        :type subtitle: dict or None
        :return: New asset with converted essence
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name:
            raise UnsupportedFormatError(f'Unsupported asset type: {mime_type}')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-loglevel', 'error', '-i', ctx.input_path]

            format_config = dict(self.config.get(mime_type.type or '', {}))
            if mime_type.type == 'video':
                keyframe_interval = int(format_config.get('keyframe_interval', 100))
                command.extend(['-g', str(keyframe_interval)])

            if video:
                if 'codec' in video:
                    if video['codec']:
                        command.extend(['-c:v', video['codec']])
                        codec_options = dict(FFmpegProcessor.__codec_options.get('video', {}).get(video['codec'], []))
                        codec_config = self.config.get(f'codec/{video["codec"]}', {})
                        if 'crf' in codec_config:
                            codec_options['crf'] = int(codec_config['crf'])
                        command.extend(_param_map_to_seq(codec_options))
                    else:
                        command.extend(['-vn'])
                if video.get('bitrate'):
                    # Set minimum at 50% of bitrate and maximum at 145% of bitrate
                    # (see https://developers.google.com/media/vp9/settings/vod/)
                    command.extend(
                        [
                            '-minrate',
                            f'{round(0.5 * video["bitrate"]):d}k',
                            '-b:v',
                            f'{video["bitrate"]:d}k',
                            '-maxrate',
                            f'{round(1.45 * video["bitrate"]):d}k',
                        ]
                    )
                if video.get('color_space') or video.get('depth') or video.get('data_type'):
                    color_mode = (
                        video.get('color_space', asset.video.get('color_space', 'YUV')),
                        video.get('depth', asset.video.get('depth', 8)),
                        video.get('data_type', asset.video.get('data_type', 'uint')),
                    )
                    ffmpeg_pix_fmt = FFmpegProcessor.__color_mode_to_ffmpeg_pix_fmt.get(color_mode)
                    if ffmpeg_pix_fmt:
                        command.extend(['-pix_fmt', ffmpeg_pix_fmt])
            if audio:
                if 'codec' in audio:
                    if audio['codec']:
                        command.extend(['-c:a', audio['codec']])
                        codec_options = FFmpegProcessor.__codec_options.get('audio', {}).get(audio['codec'], [])
                        command.extend(codec_options)
                    else:
                        command.extend(['-an'])
                if audio.get('bitrate'):
                    command.extend(['-b:a', f'{audio["bitrate"]:d}k'])
            if subtitle:
                if 'codec' in subtitle:
                    if subtitle['codec']:
                        command.extend(['-c:s', subtitle['codec']])
                        codec_options = FFmpegProcessor.__codec_options.get('subtitles', {})
                        command.extend(codec_options.get(subtitle['codec'], []))
                    else:
                        command.extend(['-sn'])

            container_options = FFmpegProcessor.__container_options.get(mime_type, [])
            container_config = self.config.get(str(mime_type), {})
            if mime_type == 'video/quicktime':
                use_faststart = container_config.get('faststart', True)
                if use_faststart:
                    container_options.extend(['-movflags', '+faststart'])
            command.extend(container_options)

            command.extend(['-threads', str(self._threads), '-f', encoder_name, '-y', ctx.output_path])

            if progress_callback is not None:
                _run_ffmpeg_with_progress(command, progress_callback)
            else:
                try:
                    subprocess.run(command, stderr=subprocess.PIPE, check=True)
                except subprocess.CalledProcessError as ffmpeg_error:
                    raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'convert asset'))

        return self.read(result)

    @operator
    def trim(self, asset: Asset, from_seconds: float = 0, to_seconds: float = 0) -> Asset:
        """
        Creates a trimmed audio or video asset that only contains the data
        between from_seconds and to_seconds.

        :param asset: Audio or video asset, which will serve as the source
        :type asset: Asset
        :param from_seconds: Start time of the clip in seconds
        :type from_seconds: float
        :param to_seconds: End time of the clip in seconds
        :type to_seconds: float
        :return: New asset with trimmed essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type not in ('audio', 'video'):
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        if to_seconds <= 0:
            to_seconds = asset.duration + to_seconds

        duration = float(to_seconds) - float(from_seconds)

        if duration <= 0:
            raise ValueError('Start time must be before end time')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = [
                'ffmpeg',
                '-v',
                'error',
                '-ss',
                str(float(from_seconds)),
                '-t',
                str(duration),
                '-i',
                ctx.input_path,
                '-codec',
                'copy',
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'trim asset'))

        metadata = _combine_metadata(
            asset, 'mime_type', 'width', 'height', 'video', 'audio', 'subtitle', duration=duration
        )

        return Asset(essence=result, **metadata)

    @operator
    def extract_frame(self, asset: Asset, mime_type: MimeType | str, seconds: float = 0) -> Asset:
        """
        Creates a new image asset of the specified MIME type from the essence
        of the specified video asset.

        :param asset: Video asset which will serve as the source for the frame
        :type asset: Asset
        :param mime_type: MIME type of the destination image
        :type mime_type: MimeType or str
        :param seconds: Offset of the frame in seconds
        :type seconds: float
        :return: New image asset with converted essence
        :rtype: Asset
        """
        source_mime_type = MimeType(asset.mime_type)
        if source_mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {source_mime_type}')

        mime_type = MimeType(mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        codec_name = self.__mime_type_to_codec.get(mime_type)
        if not (encoder_name and codec_name):
            raise UnsupportedFormatError(f'Unsupported target asset type: {mime_type}')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = [
                'ffmpeg',
                '-v',
                'error',
                '-i',
                ctx.input_path,
                '-ss',
                str(float(seconds)),
                '-codec:v',
                codec_name,
                '-vframes',
                '1',
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'extract frame from asset'))

        metadata = _combine_metadata(asset, 'width', 'height', mime_type=str(mime_type))
        if 'video' in asset.metadata:
            metadata['depth'] = asset.metadata['video']['depth']

        return Asset(essence=result, **metadata)

    @operator
    def crop(self, asset: Asset, *, x: int, y: int, width: int, height: int) -> Asset:
        """
        Creates a cropped video asset whose essence is cropped to the specified
        rectangular area.

        :param asset: Video asset whose contents will be cropped
        :type asset: Asset
        :param x: Horizontal offset of the cropping area from left
        :type x: int
        :param y: Vertical offset of the cropping area from top
        :type y: int
        :param width: Width of the cropping area
        :type width: int
        :param height: Height of the cropping area
        :type height: int
        :return: New asset with cropped essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        if x == 0 and y == 0 and width == asset.width and height == asset.height:
            return asset

        max_x = max(0, min(asset.width, width + x))
        max_y = max(0, min(asset.height, height + y))
        min_x = max(0, min(asset.width, x))
        min_y = max(0, min(asset.height, y))

        if min_x == asset.width or min_y == asset.height or max_x <= min_x or max_y <= min_y:
            raise OperatorError(f'Invalid cropping area: <x={x!r}, y={y!r}, width={width!r}, height={height!r}>')

        width = max_x - min_x
        height = max_y - min_y

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = [
                'ffmpeg',
                '-v',
                'error',
                '-i',
                ctx.input_path,
                '-filter:v',
                f'crop=w={width:d}:h={height:d}:x={min_x:d}:y={min_y:d}',
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'crop asset'))

        metadata = _combine_metadata(
            asset, 'mime_type', 'duration', 'video', 'audio', 'subtitle', width=width, height=height
        )

        return Asset(essence=result, **metadata)

    @operator
    def set_speed(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new audio or video asset whose playback speed is scaled by
        *factor* relative to the source.

        A *factor* greater than ``1.0`` speeds up playback (timelapse); a
        factor less than ``1.0`` slows it down (slow motion).  The output
        duration equals ``source_duration / factor``.

        For video streams the ``setpts`` filter is used.  For audio streams
        the ``atempo`` filter is used; because ``atempo`` accepts values only
        in ``[0.5, 2.0]``, the filter is chained automatically for extreme
        factors.

        :param asset: Audio or video asset to retime
        :type asset: Asset
        :param factor: Speed multiplier; must be positive and non-zero
        :type factor: float
        :return: New asset with adjusted playback speed
        :rtype: Asset
        :raises ValueError: If *factor* is not positive
        :raises UnsupportedFormatError: If the asset type is not supported
        """
        if factor <= 0:
            raise ValueError(f'Speed factor must be positive, got {factor!r}')

        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type not in ('audio', 'video'):
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        has_video = 'video' in asset.metadata
        has_audio = 'audio' in asset.metadata

        # Build the atempo filter chain for the audio stream.
        # The atempo filter accepts values only in [0.5, 2.0], so break the
        # factor into a chain of steps that each stay within that range.
        def _atempo_chain(f: float) -> str:
            steps: list[str] = []
            while f < 0.5:
                steps.append('atempo=0.5')
                f /= 0.5
            while f > 2.0:
                steps.append('atempo=2.0')
                f /= 2.0
            steps.append(f'atempo={f}')
            return ','.join(steps)

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-loglevel', 'error', '-i', ctx.input_path]

            if has_video:
                # setpts: scale presentation timestamps so duration changes
                command.extend(['-filter:v', f'setpts={1.0 / factor}*PTS'])
            if has_audio:
                command.extend(['-filter:a', _atempo_chain(factor)])

            command.extend(['-threads', str(self._threads), '-f', encoder_name, '-y', ctx.output_path])

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'set speed of asset'))

        duration = asset.duration / factor if hasattr(asset, 'duration') and asset.duration else None
        metadata = _combine_metadata(
            asset,
            'mime_type',
            'width',
            'height',
            'video',
            'audio',
            'subtitle',
            **({'duration': duration} if duration is not None else {}),
        )

        return Asset(essence=result, **metadata)

    @operator
    def rotate(self, asset: Asset, angle: float, expand: bool = False) -> Asset:
        """
        Creates an asset whose essence is rotated by the specified angle in
        degrees.

        :param asset: Asset whose contents will be rotated
        :type asset: Asset
        :param angle: Angle in degrees, counter clockwise
        :type angle: float
        :param expand: If true, changes the dimensions of the new asset so it
            can hold the entire rotated essence, otherwise the dimensions of
            the original asset will be used.
        :type expand: bool
        :return: New asset with rotated essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        if angle % 360.0 == 0.0:
            return asset

        angle_rad = radians(angle)
        width = asset.width
        height = asset.height

        if expand:
            if angle % 180 < 90:
                width_ = asset.width
                height_ = asset.height
                angle_rad_ = angle_rad % pi
            else:
                width_ = asset.height
                height_ = asset.width
                angle_rad_ = angle_rad % pi - pi / 2
            cos_a = cos(angle_rad_)
            sin_a = sin(angle_rad_)
            width = ceil(round(width_ * cos_a + height_ * sin_a, 7))
            height = ceil(round(width_ * sin_a + height_ * cos_a, 7))
            # Most video codecs require even dimensions
            width += width % 2
            height += height % 2

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = [
                'ffmpeg',
                '-v',
                'error',
                '-i',
                ctx.input_path,
                '-filter:v',
                f'rotate=a={angle_rad:f}:ow={width:d}:oh={height:d}',
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'rotate asset'))

        metadata = _combine_metadata(
            asset, 'mime_type', 'duration', 'video', 'audio', 'subtitle', width=width, height=height
        )

        return Asset(essence=result, **metadata)

    @operator
    def normalize_audio(self, asset: Asset, target_lufs: float = -23.0) -> Asset:
        """
        Creates a new asset whose audio stream is loudness-normalized to
        *target_lufs* LUFS (EBU R128).

        Uses a two-pass approach with the FFmpeg ``loudnorm`` filter.  The
        first pass measures integrated loudness, LRA, and true peak; the
        second pass applies a linear gain correction using those measurements
        for accurate normalization without re-quantizing the signal
        unnecessarily.

        :param asset: Audio or video asset to normalize
        :type asset: Asset
        :param target_lufs: Target integrated loudness in LUFS
        :type target_lufs: float
        :return: New asset with normalized audio
        :rtype: Asset
        :raises UnsupportedFormatError: If the asset type is not supported
        :raises OperatorError: If loudness measurement or normalization fails
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type not in ('audio', 'video'):
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            # First pass: measure integrated loudness and write measurements to
            # stderr as JSON.  The null muxer discards the output entirely.
            measure_cmd = [
                'ffmpeg',
                '-loglevel',
                'info',
                '-i',
                ctx.input_path,
                '-af',
                f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5:print_format=json',
                '-f',
                'null',
                '-',
            ]
            measure_result = subprocess.run(measure_cmd, capture_output=True)
            stderr_text = measure_result.stderr.decode('utf-8', errors='replace')

            # The JSON block is the last {...} in the filter's stderr output.
            json_start = stderr_text.rfind('{')
            json_end = stderr_text.rfind('}')
            if json_start == -1 or json_end == -1:
                raise OperatorError('Could not parse loudnorm measurements from FFmpeg output')
            try:
                loudnorm_data = json.loads(stderr_text[json_start : json_end + 1])
            except json.JSONDecodeError as exc:
                raise OperatorError(f'Invalid loudnorm JSON: {exc}') from exc

            # Check whether the measurement values are finite.  Very short
            # clips (< ~400 ms) can produce "inf" or "-inf" because the EBU
            # R128 integration window is 400 ms; passing those values to the
            # second-pass filter causes an ERANGE error.
            def _is_finite_str(s: str) -> bool:
                try:
                    return isfinite(float(s))
                except (ValueError, TypeError):
                    return False

            measurement_keys = ('input_i', 'input_lra', 'input_tp', 'input_thresh', 'target_offset')
            measurements_valid = all(_is_finite_str(loudnorm_data.get(k, 'inf')) for k in measurement_keys)

            if measurements_valid:
                # Second pass: apply linear normalization using the measured values.
                af = (
                    f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5'
                    f':measured_I={loudnorm_data["input_i"]}'
                    f':measured_LRA={loudnorm_data["input_lra"]}'
                    f':measured_TP={loudnorm_data["input_tp"]}'
                    f':measured_thresh={loudnorm_data["input_thresh"]}'
                    f':offset={loudnorm_data["target_offset"]}'
                    ':linear=true:print_format=summary'
                )
            else:
                # Fall back to single-pass dynamic normalization for clips
                # that are too short for integrated loudness measurement.
                af = f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5'

            normalize_cmd = [
                'ffmpeg',
                '-loglevel',
                'error',
                '-i',
                ctx.input_path,
                '-af',
                af,
            ]
            # Preserve the video stream unchanged when present; without this
            # flag FFmpeg would attempt to re-encode video with default
            # settings, which often fails for unusual pixel formats.
            if 'video' in asset.metadata:
                normalize_cmd.extend(['-c:v', 'copy'])
            normalize_cmd.extend(
                [
                    '-threads',
                    str(self._threads),
                    '-f',
                    encoder_name,
                    '-y',
                    ctx.output_path,
                ]
            )
            try:
                subprocess.run(normalize_cmd, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'normalize audio'))

        metadata = _combine_metadata(asset, 'mime_type', 'width', 'height', 'duration', 'video', 'audio', 'subtitle')
        return Asset(essence=result, **metadata)

    @operator
    def thumbnail_sprite(
        self,
        asset: Asset,
        columns: int,
        rows: int,
        thumb_width: int,
        thumb_height: int,
        mime_type: MimeType | str = 'image/jpeg',
    ) -> Asset:
        """
        Extracts ``columns × rows`` evenly-spaced frames from *asset* and
        stitches them into a single sprite-sheet image.

        The returned image asset has dimensions ``(columns × thumb_width) ×
        (rows × thumb_height)``.  Its metadata includes a ``'sprite'`` dict
        with the grid parameters, which can be used by the application layer
        to generate a WebVTT thumbnail track.

        :param asset: Source video asset
        :type asset: Asset
        :param columns: Number of thumbnail columns in the sprite sheet
        :type columns: int
        :param rows: Number of thumbnail rows in the sprite sheet
        :type rows: int
        :param thumb_width: Width of each thumbnail in pixels
        :type thumb_width: int
        :param thumb_height: Height of each thumbnail in pixels
        :type thumb_height: int
        :param mime_type: MIME type of the output image (default ``image/jpeg``)
        :type mime_type: MimeType or str
        :return: Image asset containing the sprite sheet
        :rtype: Asset
        :raises UnsupportedFormatError: If the source asset is not a video
        """
        source_mime = MimeType(asset.mime_type)
        source_encoder = self.__mime_type_to_encoder.get(source_mime)
        if not source_encoder or source_mime.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {source_mime}')

        mime_type = MimeType(mime_type)
        target_encoder = self.__mime_type_to_encoder.get(mime_type)
        if not target_encoder or mime_type.type != 'image':
            raise UnsupportedFormatError(f'Unsupported sprite output type: {mime_type}')

        n_frames = columns * rows
        duration = asset.duration if hasattr(asset, 'duration') and asset.duration else 1.0
        interval = duration / n_frames

        with _FFmpegContext(asset.essence, io.BytesIO()) as ctx:
            frame_dir = ctx.input_path + '_frames'
            os.makedirs(frame_dir, exist_ok=True)

            # Extract n_frames evenly-spaced frames as JPEG files.
            command = [
                'ffmpeg',
                '-loglevel',
                'error',
                '-i',
                ctx.input_path,
                '-vf',
                f'fps=1/{interval},scale={thumb_width}:{thumb_height},trim=end_frame={n_frames}',
                '-qscale:v',
                '2',
                '-f',
                'image2',
                '-y',
                os.path.join(frame_dir, 'frame_%04d.jpg'),
            ]
            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'extract sprite frames'))

            # Collect extracted frames; pad with blank frames if fewer were
            # produced than requested (can happen for very short clips).
            frame_paths = sorted(os.path.join(frame_dir, f) for f in os.listdir(frame_dir) if f.endswith('.jpg'))
            blank = PIL.Image.new('RGB', (thumb_width, thumb_height), (0, 0, 0))
            frames: list[PIL.Image.Image] = []
            for path in frame_paths[:n_frames]:
                frames.append(PIL.Image.open(path).convert('RGB'))
            while len(frames) < n_frames:
                frames.append(blank.copy())

            # Stitch frames into the sprite sheet.
            sprite_w = columns * thumb_width
            sprite_h = rows * thumb_height
            sheet = PIL.Image.new('RGB', (sprite_w, sprite_h))
            for idx, frame in enumerate(frames):
                col = idx % columns
                row = idx // columns
                sheet.paste(frame, (col * thumb_width, row * thumb_height))

            buf = io.BytesIO()
            pil_format = self.__mime_type_to_pillow_format(mime_type)
            sheet.save(buf, format=pil_format)
            buf.seek(0)

        sprite_metadata = {
            'columns': columns,
            'rows': rows,
            'thumb_width': thumb_width,
            'thumb_height': thumb_height,
            'interval_seconds': interval,
        }
        return Asset(
            essence=buf,
            mime_type=str(mime_type),
            width=sprite_w,
            height=sprite_h,
            sprite=sprite_metadata,
        )

    @staticmethod
    def __mime_type_to_pillow_format(mime_type: MimeType) -> str:
        """Map a MIME type to the Pillow format string used by ``Image.save``."""
        _map = {
            MimeType('image/jpeg'): 'JPEG',
            MimeType('image/png'): 'PNG',
            MimeType('image/webp'): 'WebP',
            MimeType('image/gif'): 'GIF',
            MimeType('image/bmp'): 'BMP',
            MimeType('image/tiff'): 'TIFF',
        }
        fmt = _map.get(mime_type)
        if not fmt:
            raise UnsupportedFormatError(f'Unsupported sprite output type: {mime_type}')
        return fmt

    @operator
    def overlay(
        self,
        asset: Asset,
        overlay_asset: Asset,
        x: int = 0,
        y: int = 0,
        gravity: str = 'north_west',
        from_seconds: float | None = None,
        to_seconds: float | None = None,
    ) -> Asset:
        """
        Composites *overlay_asset* on top of *asset* at the specified position.

        Position can be set explicitly with *x* and *y* pixel offsets from the
        top-left corner, or implicitly via *gravity* (same nine-point vocabulary
        as :meth:`~madam.image.PillowProcessor.pad`).  When both *x*/*y* and
        *gravity* are meaningful, *x* and *y* act as additional offsets relative
        to the gravity anchor.

        The overlay can be restricted to a time window with *from_seconds* and
        *to_seconds*.  Outside the window the base video is shown unmodified.

        :param asset: Base video asset
        :type asset: Asset
        :param overlay_asset: Image or video asset to composite on top
        :type overlay_asset: Asset
        :param x: Horizontal pixel offset from the left edge (or gravity anchor)
        :type x: int
        :param y: Vertical pixel offset from the top edge (or gravity anchor)
        :type y: int
        :param gravity: One of ``north_west``, ``north``, ``north_east``,
            ``west``, ``center``, ``east``, ``south_west``, ``south``,
            ``south_east``
        :type gravity: str
        :param from_seconds: Start time of the overlay window in seconds;
            ``None`` means the overlay is visible from the beginning
        :type from_seconds: float or None
        :param to_seconds: End time of the overlay window in seconds;
            ``None`` means the overlay is visible until the end
        :type to_seconds: float or None
        :return: New video asset with overlay composited
        :rtype: Asset
        :raises UnsupportedFormatError: If the base asset type is not supported
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        # Resolve gravity to pixel offsets for the overlay origin.
        overlay_w = overlay_asset.width if hasattr(overlay_asset, 'width') else 0
        overlay_h = overlay_asset.height if hasattr(overlay_asset, 'height') else 0
        gravity_offsets = {
            'north_west': (0, 0),
            'north': (asset.width // 2 - overlay_w // 2, 0),
            'north_east': (asset.width - overlay_w, 0),
            'west': (0, asset.height // 2 - overlay_h // 2),
            'center': (asset.width // 2 - overlay_w // 2, asset.height // 2 - overlay_h // 2),
            'east': (asset.width - overlay_w, asset.height // 2 - overlay_h // 2),
            'south_west': (0, asset.height - overlay_h),
            'south': (asset.width // 2 - overlay_w // 2, asset.height - overlay_h),
            'south_east': (asset.width - overlay_w, asset.height - overlay_h),
        }
        gx, gy = gravity_offsets.get(gravity, (0, 0))
        px, py = gx + x, gy + y

        # Build the enable expression for time-windowed overlay.
        enable_parts: list[str] = []
        if from_seconds is not None:
            enable_parts.append(f'gte(t,{from_seconds})')
        if to_seconds is not None:
            enable_parts.append(f'lte(t,{to_seconds})')
        enable_expr = ':'.join(enable_parts) if enable_parts else '1'

        overlay_filter = f"overlay={px}:{py}:enable='{enable_expr}'"

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            # Write the overlay asset to a second temp file in the same tmpdir.
            overlay_path = ctx.input_path + '_overlay'
            with open(overlay_path, 'wb') as fh:
                shutil.copyfileobj(overlay_asset.essence, fh)
                overlay_asset.essence.seek(0)

            command = [
                'ffmpeg',
                '-loglevel',
                'error',
                '-i',
                ctx.input_path,
                '-i',
                overlay_path,
                '-filter_complex',
                f'[0:v][1:v]{overlay_filter}[v]',
                '-map',
                '[v]',
                '-map',
                '0:a?',
                '-codec:a',
                'copy',
                '-threads',
                str(self._threads),
                '-f',
                encoder_name,
                '-y',
                ctx.output_path,
            ]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'overlay asset'))

        metadata = _combine_metadata(asset, 'mime_type', 'width', 'height', 'duration', 'video', 'audio', 'subtitle')
        return Asset(essence=result, **metadata)

    def to_hls(
        self,
        asset: Asset,
        output: MultiFileOutput,
        segment_duration: float = 6,
        video: Mapping[str, Any] | None = None,
        audio: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Transcodes *asset* to HLS (HTTP Live Streaming) format and writes all
        output files to *output*.

        The output consists of an M3U8 playlist and one or more MPEG-TS
        segment files.  Stream options can be provided via *video* and *audio*;
        by default the video is encoded as H.264 and audio as AAC, which are
        the most widely supported codecs for HLS.

        :param asset: Source video asset
        :type asset: Asset
        :param output: Destination for the playlist and segment files
        :type output: MultiFileOutput
        :param segment_duration: Target segment duration in seconds
        :type segment_duration: float
        :param video: Optional video stream options (``codec``, ``bitrate``)
        :type video: dict or None
        :param audio: Optional audio stream options (``codec``, ``bitrate``)
        :type audio: dict or None
        :raises UnsupportedFormatError: If the source asset is not a video
        """
        mime_type = MimeType(asset.mime_type)
        if mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        video_codec = (video or {}).get('codec', 'libx264')
        audio_codec = (audio or {}).get('codec', 'aac')
        video_bitrate = (video or {}).get('bitrate')
        audio_bitrate = (audio or {}).get('bitrate')

        with tempfile.TemporaryDirectory(prefix='madam_hls') as tmpdir:
            input_path = os.path.join(tmpdir, 'input')
            with open(input_path, 'wb') as fh:
                shutil.copyfileobj(asset.essence, fh)
                asset.essence.seek(0)

            playlist_path = os.path.join(tmpdir, 'index.m3u8')
            segment_pattern = os.path.join(tmpdir, 'segment_%03d.ts')

            command = ['ffmpeg', '-loglevel', 'error', '-i', input_path]
            if video_codec:
                command.extend(['-c:v', video_codec])
            if video_bitrate:
                command.extend(['-b:v', f'{video_bitrate}k'])
            if audio_codec:
                command.extend(['-c:a', audio_codec])
            if audio_bitrate:
                command.extend(['-b:a', f'{audio_bitrate}k'])
            command.extend(
                [
                    '-f',
                    'hls',
                    '-hls_time',
                    str(segment_duration),
                    '-hls_list_size',
                    '0',
                    '-hls_segment_filename',
                    segment_pattern,
                    '-threads',
                    str(self._threads),
                    '-y',
                    playlist_path,
                ]
            )

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'create HLS output'))

            # Write all generated files to the MultiFileOutput.
            for filename in os.listdir(tmpdir):
                if filename == 'input':
                    continue
                file_path = os.path.join(tmpdir, filename)
                with open(file_path, 'rb') as fh:
                    output.write(filename, fh.read())
            output.close()

    def to_dash(
        self,
        asset: Asset,
        output: MultiFileOutput,
        segment_duration: float = 6,
        video: Mapping[str, Any] | None = None,
        audio: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Transcodes *asset* to MPEG-DASH format and writes all output files
        to *output*.

        The output consists of an MPD manifest and one or more MP4 segment
        files.  Stream options can be provided via *video* and *audio*; by
        default the video is encoded as H.264 and audio as AAC.

        :param asset: Source video asset
        :type asset: Asset
        :param output: Destination for the manifest and segment files
        :type output: MultiFileOutput
        :param segment_duration: Target segment duration in seconds
        :type segment_duration: float
        :param video: Optional video stream options (``codec``, ``bitrate``)
        :type video: dict or None
        :param audio: Optional audio stream options (``codec``, ``bitrate``)
        :type audio: dict or None
        :raises UnsupportedFormatError: If the source asset is not a video
        """
        mime_type = MimeType(asset.mime_type)
        if mime_type.type != 'video':
            raise UnsupportedFormatError(f'Unsupported source asset type: {mime_type}')

        video_codec = (video or {}).get('codec', 'libx264')
        audio_codec = (audio or {}).get('codec', 'aac')
        video_bitrate = (video or {}).get('bitrate')
        audio_bitrate = (audio or {}).get('bitrate')

        with tempfile.TemporaryDirectory(prefix='madam_dash') as tmpdir:
            input_path = os.path.join(tmpdir, 'input')
            with open(input_path, 'wb') as fh:
                shutil.copyfileobj(asset.essence, fh)
                asset.essence.seek(0)

            manifest_path = os.path.join(tmpdir, 'manifest.mpd')

            command = ['ffmpeg', '-loglevel', 'error', '-i', input_path]
            if video_codec:
                command.extend(['-c:v', video_codec])
            if video_bitrate:
                command.extend(['-b:v', f'{video_bitrate}k'])
            if audio_codec:
                command.extend(['-c:a', audio_codec])
            if audio_bitrate:
                command.extend(['-b:a', f'{audio_bitrate}k'])
            command.extend(
                [
                    '-f',
                    'dash',
                    '-seg_duration',
                    str(segment_duration),
                    '-threads',
                    str(self._threads),
                    '-y',
                    manifest_path,
                ]
            )

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'create DASH output'))

            # Write all generated files to the MultiFileOutput.
            for filename in os.listdir(tmpdir):
                if filename == 'input':
                    continue
                file_path = os.path.join(tmpdir, filename)
                with open(file_path, 'rb') as fh:
                    output.write(filename, fh.read())
            output.close()


def concatenate(
    assets: Iterable[Asset],
    mime_type: MimeType | str,
    video: Mapping[str, Any] | None = None,
    audio: Mapping[str, Any] | None = None,
) -> Asset:
    """
    Joins a sequence of audio or video assets end-to-end into a single asset.

    Assets are concatenated in the order they appear in *assets*.  By default
    the streams are copied without re-encoding (``-c copy``).  Provide *video*
    and/or *audio* stream options to force re-encoding, which is required when
    the source clips use different codecs.

    Uses the FFmpeg ``concat`` demuxer, which supports any format that can be
    read from files.

    :param assets: Iterable of assets to concatenate; must be non-empty
    :type assets: Iterable[Asset]
    :param mime_type: MIME type of the output container
    :type mime_type: MimeType or str
    :param video: Optional video stream options (same keys as
        :meth:`FFmpegProcessor.convert`)
    :type video: dict or None
    :param audio: Optional audio stream options (same keys as
        :meth:`FFmpegProcessor.convert`)
    :type audio: dict or None
    :return: New asset with concatenated essence
    :rtype: Asset
    :raises ValueError: If *assets* is empty

    .. versionadded:: 0.24
    :raises UnsupportedFormatError: If *mime_type* is not supported
    """
    asset_list = list(assets)
    if not asset_list:
        raise ValueError('Cannot concatenate an empty sequence of assets')

    mime_type = MimeType(mime_type)

    # Lazy import to avoid a circular dependency; processor is only used for
    # its encoder map and read() method.
    processor = FFmpegProcessor()
    encoder_name = processor._FFmpegProcessor__mime_type_to_encoder.get(mime_type)  # type: ignore[attr-defined]
    if not encoder_name:
        raise UnsupportedFormatError(f'Unsupported output type: {mime_type}')

    with tempfile.TemporaryDirectory(prefix='madam_concat') as tmpdir:
        # Write each essence to a numbered temp file.
        input_paths: list[str] = []
        for idx, asset in enumerate(asset_list):
            path = os.path.join(tmpdir, f'input_{idx:04d}')
            with open(path, 'wb') as fh:
                shutil.copyfileobj(asset.essence, fh)
                asset.essence.seek(0)
            input_paths.append(path)

        # Write the concat demuxer list file.
        list_path = os.path.join(tmpdir, 'concat.txt')
        with open(list_path, 'w') as fh:
            for path in input_paths:
                fh.write(f"file '{path}'\n")

        output_path = os.path.join(tmpdir, 'output_file')
        command = [
            'ffmpeg',
            '-loglevel',
            'error',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            list_path,
        ]

        if video:
            if 'codec' in video:
                if video['codec']:
                    command.extend(['-c:v', video['codec']])
                else:
                    command.extend(['-vn'])
            if video.get('bitrate'):
                command.extend(['-b:v', f'{video["bitrate"]:d}k'])
        if audio:
            if 'codec' in audio:
                if audio['codec']:
                    command.extend(['-c:a', audio['codec']])
                else:
                    command.extend(['-an'])
            if audio.get('bitrate'):
                command.extend(['-b:a', f'{audio["bitrate"]:d}k'])

        if not video and not audio:
            # Default: stream copy — fast and lossless when codecs match.
            command.extend(['-c', 'copy'])

        command.extend(['-f', encoder_name, '-y', output_path])

        try:
            subprocess.run(command, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as ffmpeg_error:
            raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'concatenate assets'))

        result = io.BytesIO()
        with open(output_path, 'rb') as fh:
            shutil.copyfileobj(fh, result)
        result.seek(0)

    return processor.read(result)


# Video-only MIME types supported by combine().
_COMBINE_VIDEO_MIME_TYPES: frozenset[MimeType] = frozenset(
    {
        MimeType('video/mp4'),
        MimeType('video/webm'),
        MimeType('video/x-matroska'),
        MimeType('video/quicktime'),
        MimeType('video/x-msvideo'),
        MimeType('video/mp2t'),
        MimeType('video/x-nut'),
        MimeType('video/ogg'),
    }
)

# Default video codec per output container for combine().
_COMBINE_DEFAULT_VIDEO_CODEC: dict[MimeType, str] = {
    MimeType('video/mp4'): VideoCodec.H264,
    MimeType('video/quicktime'): VideoCodec.H264,
    MimeType('video/webm'): VideoCodec.VP9,
    MimeType('video/x-matroska'): VideoCodec.VP9,
    MimeType('video/x-msvideo'): VideoCodec.H264,
    MimeType('video/mp2t'): VideoCodec.H264,
    MimeType('video/x-nut'): VideoCodec.H264,
    MimeType('video/ogg'): VideoCodec.VP8,
}


def combine(
    assets: Iterable[Asset],
    mime_type: MimeType | str,
    *,
    fps: float = 24.0,
    video: Mapping[str, Any] | None = None,
    audio: Mapping[str, Any] | None = None,
) -> Asset:
    """
    Assembles a sequence of image (or video) assets into a video by treating
    each asset as one frame at a fixed frame rate.

    Each asset's essence is written to a temporary file and listed in an FFmpeg
    concat-demuxer playlist.  The ``duration`` of each entry is computed from
    *fps* so that the resulting clip plays at the specified frame rate.

    :param assets: Iterable of assets to use as frames; must be non-empty
    :type assets: Iterable[Asset]
    :param mime_type: MIME type of the output video container
    :type mime_type: MimeType or str
    :param fps: Frames per second (must be positive; default 24.0)
    :type fps: float
    :param video: Optional video stream options (same keys as
        :meth:`FFmpegProcessor.convert`; e.g. ``{'codec': VideoCodec.H264}``)
    :type video: dict or None
    :param audio: Optional audio stream options
    :type audio: dict or None
    :return: New video asset
    :rtype: Asset
    :raises ValueError: If *assets* is empty or *fps* ≤ 0
    :raises UnsupportedFormatError: If *mime_type* is not a supported video format
    :raises OperatorError: If FFmpeg fails

    .. versionadded:: 1.0
    """
    asset_list = list(assets)
    if not asset_list:
        raise ValueError('Cannot combine an empty sequence of assets')
    if fps <= 0:
        raise ValueError(f'fps must be positive, got {fps!r}')

    mime_type = MimeType(mime_type)
    if mime_type not in _COMBINE_VIDEO_MIME_TYPES:
        raise UnsupportedFormatError(f'Unsupported video output type: {mime_type}')

    processor = FFmpegProcessor()
    encoder_name = processor._FFmpegProcessor__mime_type_to_encoder.get(mime_type)  # type: ignore[attr-defined]

    frame_duration = 1.0 / fps

    with tempfile.TemporaryDirectory(prefix='madam_combine') as tmpdir:
        input_paths: list[str] = []
        for idx, asset in enumerate(asset_list):
            path = os.path.join(tmpdir, f'input_{idx:04d}')
            with open(path, 'wb') as fh:
                shutil.copyfileobj(asset.essence, fh)
                asset.essence.seek(0)
            input_paths.append(path)

        list_path = os.path.join(tmpdir, 'concat.txt')
        with open(list_path, 'w') as fh:
            for path in input_paths:
                fh.write(f"file '{path}'\n")
                fh.write(f'duration {frame_duration:.6f}\n')

        output_path = os.path.join(tmpdir, 'output_file')
        command = [
            'ffmpeg',
            '-loglevel',
            'error',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            list_path,
        ]

        # Force the output to be encoded at the requested frame rate.  This
        # ensures the concat-demuxer timestamps from the 'duration' lines are
        # honoured correctly even for still-image inputs.
        command.extend(['-vf', f'fps={fps}'])

        if video:
            if 'codec' in video:
                if video['codec']:
                    command.extend(['-c:v', video['codec']])
                else:
                    command.extend(['-vn'])
            if video.get('bitrate'):
                command.extend(['-b:v', f'{video["bitrate"]:d}k'])
        else:
            default_codec = _COMBINE_DEFAULT_VIDEO_CODEC.get(mime_type, VideoCodec.H264)
            command.extend(['-c:v', default_codec])

        if audio:
            if 'codec' in audio:
                if audio['codec']:
                    command.extend(['-c:a', audio['codec']])
                else:
                    command.extend(['-an'])
            if audio.get('bitrate'):
                command.extend(['-b:a', f'{audio["bitrate"]:d}k'])
        else:
            command.extend(['-an'])

        command.extend(['-f', encoder_name, '-y', output_path])

        try:
            subprocess.run(command, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as ffmpeg_error:
            raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'combine assets'))

        result = io.BytesIO()
        with open(output_path, 'rb') as fh:
            shutil.copyfileobj(fh, result)
        result.seek(0)

    return processor.read(result)


class FFmpegMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor that uses FFmpeg.
    """

    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): MimeType('video/x-matroska'),
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): MimeType('video/quicktime'),
        ('avi', 'video'): MimeType('video/x-msvideo'),
        ('mpegts', 'video'): MimeType('video/mp2t'),
        ('ogg', 'video'): MimeType('video/ogg'),
        ('mp3', 'audio'): MimeType('audio/mpeg'),
        ('ogg', 'audio'): MimeType('audio/ogg'),
        ('wav', 'audio'): MimeType('audio/wav'),
    }

    __mime_type_to_encoder = {
        MimeType('video/x-matroska'): 'matroska',
        MimeType('video/quicktime'): 'mov',
        MimeType('video/x-msvideo'): 'avi',
        MimeType('video/mp2t'): 'mpegts',
        MimeType('video/ogg'): 'ogg',
        MimeType('audio/mpeg'): 'mp3',
        MimeType('audio/ogg'): 'ogg',
        MimeType('audio/wav'): 'wav',
    }

    # See https://wiki.multimedia.cx/index.php?title=FFmpeg_Metadata
    metadata_keys_by_mime_type = {
        # Matroska stores most tags in uppercase; 'title' is the exception.
        MimeType('video/x-matroska'): bidict(
            {
                'title': 'title',
                'artist': 'ARTIST',
                'comment': 'COMMENT',
                'copyright': 'COPYRIGHT',
                'date': 'DATE',
                'description': 'DESCRIPTION',
                'encoder': 'ENCODER',
                'genre': 'GENRE',
                'language': 'LANGUAGE',
            }
        ),
        # AVI uses lowercase INFO chunk tags.
        MimeType('video/x-msvideo'): bidict(
            {
                'title': 'title',
                'artist': 'artist',
                'comment': 'comment',
                'copyright': 'copyright',
                'date': 'date',
                'genre': 'genre',
            }
        ),
        MimeType('video/mp2t'): bidict({}),
        # QuickTime/MP4 uses lowercase atoms.
        MimeType('video/quicktime'): bidict(
            {
                'title': 'title',
                'artist': 'artist',
                'comment': 'comment',
                'copyright': 'copyright',
                'date': 'date',
                'description': 'description',
                'encoder': 'encoder',
                'genre': 'genre',
            }
        ),
        MimeType('video/ogg'): bidict({}),
        MimeType('audio/mpeg'): bidict(
            {
                'album': 'album',  # TALB Album
                'album_artist': 'album_artist',  # TPE2 Band/orchestra/accompaniment
                'album_sort': 'album-sort',  # TSOA Album sort order
                'artist': 'artist',  # TPE1 Lead performer(s)/Soloist(s)
                'artist_sort': 'artist-sort',  # TSOP Performer sort order
                'bpm': 'TBPM',  # TBPM BPM (beats per minute)
                'composer': 'composer',  # TCOM Composer
                'performer': 'performer',  # TPE3 Conductor/performer refinement
                'content_group': 'TIT1',  # TIT1 Content group description
                'copyright': 'copyright',  # TCOP (Copyright message)
                'date': 'date',  # TDRC Recording time
                'disc': 'disc',  # TPOS Part of a set
                'disc_subtitle': 'TSST',  # TSST Set subtitle
                'encoded_by': 'encoded_by',  # TENC Encoded by
                'encoder': 'encoder',  # TSSE Software/Hardware and settings used for encoding
                'encoding_time': 'TDEN',  # TDEN Encoding time
                'file_type': 'TFLT',  # TFLT File type
                'genre': 'genre',  # TCON (Content type)
                'isrc': 'TSRC',  # TSRC ISRC (international standard recording code)
                'initial_key': 'TKEY',  # TKEY Musical key in which the sound starts
                'involved_people': 'TIPL',  # TIPL Involved people list
                'language': 'language',  # TLAN Language(s)
                'length': 'TLEN',  # TLEN Length of the audio file in milliseconds
                'lyricist': 'TEXT',  # TEXT Lyricist/Text writer
                'lyrics': 'lyrics',  # USLT Unsychronized lyric/text transcription
                'media_type': 'TMED',  # TMED Media type
                'mood': 'TMOO',  # TMOO Mood
                'original_album': 'TOAL',  # TOAL Original album/movie/show title
                'original_artist': 'TOPE',  # TOPE Original artist(s)/performer(s)
                'original_date': 'TDOR',  # TDOR Original release time
                'original_filename': 'TOFN',  # TOFN Original filename
                'original_lyricist': 'TOLY',  # TOLY Original lyricist(s)/text writer(s)
                'owner': 'TOWN',  # TOWN File owner/licensee
                'credits': 'TMCL',  # TMCL Musician credits list
                'playlist_delay': 'TDLY',  # TDLY Playlist delay
                'produced_by': 'TPRO',  # TPRO Produced notice
                'publisher': 'publisher',  # TPUB Publisher
                'radio_station_name': 'TRSN',  # TRSN Internet radio station name
                'radio_station_owner': 'TRSO',  # TRSO Internet radio station owner
                'remixed_by': 'TP4',  # TPE4 Interpreted, remixed, or otherwise modified by
                'tagging_date': 'TDTG',  # TDTG Tagging time
                'title': 'title',  # TIT2 Title/songname/content description
                'title_sort': 'title-sort',  # TSOT Title sort order
                'track': 'track',  # TRCK Track number/Position in set
                'version': 'TIT3',  # TIT3 Subtitle/Description refinement
                # Release time (TDRL) can be written, but it collides with
                # recording time (TDRC) when reading;
                # AENC, APIC, ASPI, COMM, COMR, ENCR, EQU2, ETCO, GEOB, GRID, LINK,
                # MCDI, MLLT, OWNE, PRIV, PCNT, POPM, POSS, RBUF, RVA2, RVRB, SEEK,
                # SIGN, SYLT, SYTC, UFID, USER, WCOM, WCOP, WOAF, WOAR, WOAS, WORS,
                # WPAY, WPUB, and WXXX will be written as TXXX tag
            }
        ),
        MimeType('audio/ogg'): bidict(
            {
                'album': 'ALBUM',  # Collection name
                'album_artist': 'album_artist',  # Band/orchestra/accompaniment
                'artist': 'ARTIST',  # Band or singer, composer, author, etc.
                'comment': 'comment',  # Short text description of the contents
                'composer': 'COMPOSER',  # Composer
                'contact': 'CONTACT',  # Contact information for the creators or distributors
                'copyright': 'COPYRIGHT',  # Copyright attribution
                'date': 'DATE',  # Date the track was recorded
                'disc': 'disc',  # Collection number
                'encoded_by': 'ENCODED-BY',  # Encoded by
                'encoder': 'ENCODER',  # Software/Hardware and settings used for encoding
                'genre': 'GENRE',  # Short text indication of music genre
                'isrc': 'ISRC',  # ISRC number
                'license': 'LICENSE',  # License information
                'location': 'LOCATION',  # Location where track was recorded
                'performer': 'PERFORMER',  # Artist(s) who performed the work (conductor, orchestra, etc.)
                'produced_by': 'ORGANIZATION',  # Organization producing the track (i.e. the 'record label')
                'title': 'TITLE',  # Track/Work name
                'track': 'track',  # Track number if part of a collection or album
                'tracks': 'TRACKTOTAL',  # Total number of track number in a collection or album
                'version': 'VERSION',  # Version of the track (e.g. remix info)
            }
        ),
        MimeType('audio/wav'): bidict({}),
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `FFmpegMetadataProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'ffmetadata'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Extract metadata (tags) from ffprobe information
        ffmetadata = probe_data['format'].get('tags', {})
        for stream in probe_data['streams']:
            ffmetadata.update(stream.get('tags', {}))

        # Convert FFMetadata items to metadata items
        metadata = {}
        metadata_keys = self.metadata_keys_by_mime_type[mime_type]
        for ffmetadata_key, value in ffmetadata.items():
            metadata_key = metadata_keys.inv.get(ffmetadata_key)
            if metadata_key is not None:
                metadata[metadata_key] = value

        return {'ffmetadata': metadata}

    def strip(self, file: IO) -> IO:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Strip metadata
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = [
                'ffmpeg',
                '-loglevel',
                'error',
                '-i',
                ctx.input_path,
                '-map_metadata',
                '-1',
                '-codec',
                'copy',
                '-y',
                '-f',
                encoder_name,
                ctx.output_path,
            ]
            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise UnsupportedFormatError(
                    f'Could not strip metadata: format {mime_type} is not supported for metadata stripping.'
                ) from ffmpeg_error

        return result

    def combine(self, file: IO, metadata: Mapping[str, Mapping]) -> IO:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Validate provided metadata
        if not metadata:
            raise ValueError('No metadata provided')
        if 'ffmetadata' not in metadata:
            raise UnsupportedFormatError(f'Invalid metadata to be combined with essence: {metadata.keys()!r}')
        if not metadata['ffmetadata']:
            raise ValueError('No metadata provided')

        # Add metadata to file
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error', '-f', encoder_name, '-i', ctx.input_path]

            ffmetadata = metadata['ffmetadata']
            metadata_keys = self.metadata_keys_by_mime_type[mime_type]
            for metadata_key, value in ffmetadata.items():
                ffmetadata_key = metadata_keys.get(metadata_key)
                if ffmetadata_key is None:
                    raise ValueError(f'Unsupported metadata key: {metadata_key!r}')
                command.append('-metadata')
                command.append(f'{ffmetadata_key}={value}')

            command.extend(['-codec', 'copy', '-y', '-f', encoder_name, ctx.output_path])

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                raise OperatorError(_ffmpeg_error_message(ffmpeg_error, 'add metadata'))

        return result
