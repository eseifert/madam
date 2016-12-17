import io
import json
import multiprocessing
import os
import shutil
import subprocess
import tempfile

from bidict import bidict

from madam.core import Asset, MetadataProcessor, Processor, operator, OperatorError, UnsupportedFormatError
from madam.future import CalledProcessError, subprocess_run


def _probe(file):
    with tempfile.NamedTemporaryFile(mode='wb') as temp_in:
        shutil.copyfileobj(file, temp_in.file)
        temp_in.flush()
        file.seek(0)

        command = 'ffprobe -loglevel error -print_format json -show_format -show_streams'.split()
        command.append(temp_in.name)
        result = subprocess_run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)

    string_result = result.stdout.decode('utf-8')
    json_obj = json.loads(string_result)

    return json_obj


def _get_decoder_and_stream_type(probe_data):
    decoder_name = probe_data['format']['format_name']

    stream_type = ''
    for stream in probe_data['streams']:
        if stream['codec_type'] == 'video':
            stream_type = 'video'
            break
        elif stream['codec_type'] == 'audio':
            stream_type = 'audio'

    return decoder_name, stream_type


class _FFmpegContext(tempfile.TemporaryDirectory):
    def __init__(self, source, result):
        super().__init__(prefix='madam')
        self.__source = source
        self.__result = result

    def __enter__(self):
        tmpdir_path = super().__enter__()
        self.input_path = os.path.join(tmpdir_path, 'input_file')
        self.output_path = os.path.join(tmpdir_path, 'output_file')

        with open(self.input_path, 'wb') as temp_in:
            shutil.copyfileobj(self.__source, temp_in)
            self.__source.seek(0)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if os.path.exists(self.output_path):
            with open(self.output_path, 'rb') as temp_out:
                shutil.copyfileobj(temp_out, self.__result)
                self.__result.seek(0)

        super().__exit__(exc_type, exc_val, exc_tb)


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.

    The minimum version of FFmpeg required is v0.9.
    """

    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): 'video/x-matroska',
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): 'video/quicktime',
        ('ogg', 'video'): 'video/ogg',
        ('mp3', 'audio'): 'audio/mpeg',
        ('ogg', 'audio'): 'audio/ogg',
        ('wav', 'audio'): 'audio/wav',
    }

    __mime_type_to_encoder = {
        'video/x-matroska': 'matroska',
        'video/quicktime': 'mov',
        'video/ogg': 'ogg',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
        'audio/wav': 'wav',
        'image/gif': 'gif',
        'image/jpeg': 'image2',
        'image/png': 'image2',
    }

    __mime_type_to_codec = {
        'image/gif': 'gif',
        'image/jpeg': 'mjpeg',
        'image/png': 'png',
    }

    def __init__(self):
        """
        Initializes a new FFmpegProcessor.

        :raises EnvironmentError: if the installed version of ffprobe does not match the minimum version requirement
        """
        super().__init__()

        self._min_version = '0.9'
        command = 'ffprobe -version'.split()
        result = subprocess_run(command, stdout=subprocess.PIPE)
        string_result = result.stdout.decode('utf-8')
        version_string = string_result.split()[2]
        if version_string < self._min_version:
            raise EnvironmentError('Found ffprobe version %s. Requiring at least version %s.'
                                   % (version_string, self._min_version))

        self.__threads = multiprocessing.cpu_count()

    def can_read(self, file):
        try:
            probe_data = _probe(file)
            return bool(probe_data)
        except CalledProcessError:
            return False

    def read(self, file):
        try:
            probe_data = _probe(file)
        except CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        metadata = dict(
            mime_type=mime_type,
            duration=float(probe_data['format']['duration'])
        )

        for stream in probe_data['streams']:
            stream_type = stream.get('codec_type')
            if stream_type in ('audio', 'video'):
                # Only use first stream
                if stream_type in metadata:
                    break
                metadata[stream_type] = {}
            if 'codec_name' in stream:
                metadata[stream_type]['codec'] = stream['codec_name']
            if 'bit_rate' in stream:
                metadata[stream_type]['bitrate'] = float(stream['bit_rate'])/1000.0
            if 'width' in stream:
                metadata['width'] = max(stream['width'], metadata.get('width', 0))
            if 'height' in stream:
                metadata['height'] = max(stream['height'], metadata.get('height', 0))

        return Asset(essence=file, **metadata)

    @operator
    def resize(self, asset, width, height):
        """
        Creates a new image or video asset of the specified width and height
        from the essence of the specified image or video asset.

        Width and height must be positive numbers.

        :param asset: Video asset that will serve as the source for the frame
        :param width: Width of the resized asset
        :type width: int
        :param height: Height of the resized asset
        :type height: int
        :return: New asset with specified width and height
        """
        if width < 1 or height < 1:
            raise ValueError('Invalid dimensions: %dx%d' % (width, height))

        encoder_name = self.__mime_type_to_encoder.get(asset.mime_type)
        if not encoder_name:
            raise UnsupportedFormatError('Unsupported asset type: %s' % asset.mime_type)
        if asset.mime_type.split('/')[0] not in ('image', 'video'):
            raise OperatorError('Cannot resize asset of type %s')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            with open(ctx.input_path, 'wb') as temp_in:
                shutil.copyfileobj(asset.essence, temp_in)
                temp_in.flush()

            command = ['ffmpeg', '-loglevel', 'error',
                       '-f', encoder_name, '-i', ctx.input_path,
                       '-filter:v', 'scale=%d:%d' % (width, height),
                       '-threads', str(self.__threads),
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not resize video asset: %s' % error_message)

        return Asset(essence=result, mime_type=asset.mime_type,
                     width=width, height=height, duration=asset.duration)

    @operator
    def convert(self, asset, mime_type, video=None, audio=None, subtitles=None):
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
        :param mime_type: MIME type of the video container
        :param video: Dictionary with options for video streams.
        :param audio: Dictionary with options for audio streams.
        :param subtitles: Dictionary with the options for subtitle streams.
        :return: New asset with converted essence
        """
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name:
            raise UnsupportedFormatError('Unsupported asset type: %s' % mime_type)

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-loglevel', 'error',
                       '-i', ctx.input_path]
            if video is not None:
                if 'codec' in video:
                    if video['codec']:
                        command.extend(['-c:v', video['codec']])
                    else:
                        command.extend(['-vn'])
                if video.get('bitrate'):
                    command.extend(['-b:v', '%dk' % video['bitrate']])
            if audio is not None:
                if 'codec' in audio:
                    if audio['codec']:
                        command.extend(['-c:a', audio['codec']])
                    else:
                        command.extend(['-an'])
                if audio.get('bitrate'):
                    command.extend(['-b:a', '%dk' % audio['bitrate']])
            if subtitles is not None:
                if 'codec' in subtitles:
                    if subtitles['codec']:
                        command.extend(['-c:s', subtitles['codec']])
                    else:
                        command.extend(['-sn'])
            command.extend(['-threads', str(self.__threads),
                            '-f', encoder_name, '-y', ctx.output_path])

            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not convert video asset: %s' % error_message)

        metadata = {
            'mime_type': mime_type
        }
        mime_category = mime_type.split('/')[0]
        if mime_category in ('image', 'video'):
            metadata['width'] = asset.width
            metadata['height'] = asset.height
        if mime_category in ('audio', 'video'):
            metadata['duration'] = asset.duration

        return Asset(essence=result, **metadata)

    @operator
    def trim(self, asset, from_seconds=0, to_seconds=0):
        """
        Creates a trimmed audio or video asset that only contains the data
        between from_seconds and to_seconds.

        :param asset: Audio or video asset, which will serve as the source
        :param from_seconds: Start time of the clip in seconds
        :type from_seconds: float
        :param to_seconds: End time of the clip in seconds
        :type to_seconds: float
        :return: New asset with trimmed essence
        """
        encoder_name = self.__mime_type_to_encoder.get(asset.mime_type)
        if not encoder_name or not (asset.mime_type.startswith('audio/') or asset.mime_type.startswith('video/')):
            raise UnsupportedFormatError('Unsupported source asset type: %s' % asset.mime_type)

        if to_seconds <= 0:
            to_seconds = asset.duration + to_seconds

        duration = float(to_seconds) - float(from_seconds)

        if duration <= 0:
            raise ValueError('Start time must be before end time')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error',
                       '-ss', str(float(from_seconds)), '-t', str(duration),
                       '-i', ctx.input_path, '-codec', 'copy',
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not convert video asset: %s' % error_message)

        return Asset(essence=result, mime_type=asset.mime_type,
                     width=asset.width, height=asset.height, duration=duration)

    @operator
    def extract_frame(self, asset, mime_type, seconds=0):
        """
        Creates a new image asset of the specified MIME type from the essence
        of the specified video asset.

        :param asset: Video asset which will serve as the source for the frame
        :param mime_type: MIME type of the source
        :type mime_type: str
        :param seconds: Offset of the frame in seconds
        :type seconds: float
        :return: New image asset with converted essence
        """
        if not asset.mime_type.startswith('video/'):
            raise UnsupportedFormatError('Unsupported source asset type: %s' % asset.mime_type)

        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        codec_name = self.__mime_type_to_codec.get(mime_type)
        if not (encoder_name and codec_name):
            raise UnsupportedFormatError('Unsupported target asset type: %s' % mime_type)

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error', '-ss', str(float(seconds)),
                       '-i', ctx.input_path,
                       '-codec:v', codec_name, '-vframes', '1',
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not convert video asset: %s' % error_message)

        return Asset(essence=result, mime_type=mime_type,
                     width=asset.width, height=asset.height)


class FFmpegMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor that uses FFmpeg.
    """
    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): 'video/x-matroska',
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): 'video/quicktime',
        ('ogg', 'video'): 'video/ogg',
        ('mp3', 'audio'): 'audio/mpeg',
        ('ogg', 'audio'): 'audio/ogg',
        ('wav', 'audio'): 'audio/wav',
    }

    __mime_type_to_encoder = {
        'video/x-matroska': 'matroska',
        'video/quicktime': 'mov',
        'video/ogg': 'ogg',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
        'audio/wav': 'wav',
    }

    # See https://wiki.multimedia.cx/index.php?title=FFmpeg_Metadata
    metadata_keys_by_mime_type = {
        'video/x-matroska': bidict({}),
        'video/quicktime': bidict({}),
        'video/ogg': bidict({}),
        'audio/mpeg': bidict({
            'album': 'album',                   # TALB Album
            'album_artist': 'album_artist',     # TPE2 Band/orchestra/accompaniment
            'album_sort': 'album-sort',         # TSOA Album sort order
            'artist': 'artist',                 # TPE1 Lead performer(s)/Soloist(s)
            'artist_sort': 'artist-sort',       # TSOP Performer sort order
            'bpm': 'TBPM',                      # TBPM BPM (beats per minute)
            'composer': 'composer',             # TCOM Composer
            'performer': 'performer',           # TPE3 Conductor/performer refinement
            'content_group': 'TIT1',            # TIT1 Content group description
            'copyright': 'copyright',           # TCOP (Copyright message)
            'date': 'date',                     # TDRC Recording time
            'disc': 'disc',                     # TPOS Part of a set
            'disc_subtitle': 'TSST',            # TSST Set subtitle
            'encoded_by': 'encoded_by',         # TENC Encoded by
            'encoder': 'encoder',               # TSSE Software/Hardware and settings used for encoding
            'encoding_time': 'TDEN',            # TDEN Encoding time
            'file_type': 'TFLT',                # TFLT File type
            'genre': 'genre',                   # TCON (Content type)
            'isrc': 'TSRC',                     # TSRC ISRC (international standard recording code)
            'initial_key': 'TKEY',              # TKEY Musical key in which the sound starts
            'involved_people': 'TIPL',          # TIPL Involved people list
            'language': 'language',             # TLAN Language(s)
            'length': 'TLEN',                   # TLEN Length of the audio file in milliseconds
            'lyricist': 'TEXT',                 # TEXT Lyricist/Text writer
            'lyrics': 'lyrics',                 # USLT Unsychronized lyric/text transcription
            'media_type': 'TMED',               # TMED Media type
            'mood': 'TMOO',                     # TMOO Mood
            'original_album': 'TOAL',           # TOAL Original album/movie/show title
            'original_artist': 'TOPE',          # TOPE Original artist(s)/performer(s)
            'original_date': 'TDOR',            # TDOR Original release time
            'original_filename': 'TOFN',        # TOFN Original filename
            'original_lyricist': 'TOLY',        # TOLY Original lyricist(s)/text writer(s)
            'owner': 'TOWN',                    # TOWN File owner/licensee
            'credits': 'TMCL',                  # TMCL Musician credits list
            'playlist_delay': 'TDLY',           # TDLY Playlist delay
            'produced_by': 'TPRO',              # TPRO Produced notice
            'publisher': 'publisher',           # TPUB Publisher
            'radio_station_name': 'TRSN',       # TRSN Internet radio station name
            'radio_station_owner': 'TRSO',      # TRSO Internet radio station owner
            'remixed_by': 'TP4',                # TPE4 Interpreted, remixed, or otherwise modified by
            'tagging_date': 'TDTG',             # TDTG Tagging time
            'title': 'title',                   # TIT2 Title/songname/content description
            'title_sort': 'title-sort',         # TSOT Title sort order
            'track': 'track',                   # TRCK Track number/Position in set
            'version': 'TIT3',                  # TIT3 Subtitle/Description refinement

            # Release time (TDRL) can be written, but it collides with
            # recording time (TDRC) when reading;

            # AENC, APIC, ASPI, COMM, COMR, ENCR, EQU2, ETCO, GEOB, GRID, LINK,
            # MCDI, MLLT, OWNE, PRIV, PCNT, POPM, POSS, RBUF, RVA2, RVRB, SEEK,
            # SIGN, SYLT, SYTC, UFID, USER, WCOM, WCOP, WOAF, WOAR, WOAS, WORS,
            # WPAY, WPUB, and WXXX will be written as TXXX tag
        }),
        'audio/ogg': bidict({
            'album': 'ALBUM',                   # Collection name
            'album_artist': 'album_artist',     # Band/orchestra/accompaniment
            'artist': 'ARTIST',                 # Band or singer, composer, author, etc.
            'comment': 'comment',               # Short text description of the contents
            'composer': 'COMPOSER',             # Composer
            'contact': 'CONTACT',               # Contact information for the creators or distributors
            'copyright': 'COPYRIGHT',           # Copyright attribution
            'date': 'DATE',                     # Date the track was recorded
            'disc': 'disc',                     # Collection number
            'encoded_by': 'ENCODED-BY',         # Encoded by
            'encoder': 'ENCODER',               # Software/Hardware and settings used for encoding
            'genre': 'GENRE',                   # Short text indication of music genre
            'isrc': 'ISRC',                     # ISRC number
            'license': 'LICENSE',               # License information
            'location': 'LOCATION',             # Location where track was recorded
            'performer': 'PERFORMER',           # Artist(s) who performed the work (conductor, orchestra, etc.)
            'produced_by': 'ORGANIZATION',      # Organization producing the track (i.e. the 'record label')
            'title': 'TITLE',                   # Track/Work name
            'track': 'track',                   # Track number if part of a collection or album
            'tracks': 'TRACKTOTAL',             # Total number of track number in a collection or album
            'version': 'VERSION',               # Version of the track (e.g. remix info)
        }),
        'audio/wav': bidict({}),
    }

    @property
    def formats(self):
        return 'ffmetadata',

    def read(self, file):
        try:
            probe_data = _probe(file)
        except CalledProcessError:
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

    def strip(self, file):
        try:
            probe_data = _probe(file)
        except CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Strip metadata
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error',
                       '-i', ctx.input_path,
                       '-map_metadata', '-1', '-codec', 'copy',
                       '-y', '-f', encoder_name, ctx.output_path]
            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not strip metadata: %s' % error_message)

        return result

    def combine(self, file, metadata_by_type):
        try:
            probe_data = _probe(file)
        except CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Validate provided metadata
        if not metadata_by_type:
            raise ValueError('No metadata provided')
        if 'ffmetadata' not in metadata_by_type:
            raise UnsupportedFormatError('Invalid metadata to be combined with essence: %r' %
                                         (metadata_by_type.keys(),))
        if not metadata_by_type['ffmetadata']:
            raise ValueError('No metadata provided')

        # Add metadata to file
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error',
                       '-f', encoder_name, '-i', ctx.input_path]

            ffmetadata = metadata_by_type['ffmetadata']
            metadata_keys = self.metadata_keys_by_mime_type[mime_type]
            for metadata_key, value in ffmetadata.items():
                ffmetadata_key = metadata_keys.get(metadata_key)
                if ffmetadata_key is None:
                    raise ValueError('Unsupported metadata key: %r' % metadata_key)
                command.append('-metadata')
                command.append('%s=%s' % (ffmetadata_key, value))

            command.extend(['-codec', 'copy',
                            '-y', '-f', encoder_name, ctx.output_path])

            try:
                subprocess_run(command, stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not add metadata: %s' % error_message)

        return result
