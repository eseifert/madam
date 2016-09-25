import io
import json
import shutil
import subprocess
import tempfile

from bidict import bidict

from madam.core import Asset, MetadataProcessor, Processor, operator, OperatorError, UnsupportedFormatError
from madam.future import CalledProcessError, subprocess_run


def _probe(file):
    with tempfile.NamedTemporaryFile() as tmp:
        shutil.copyfileobj(file, tmp.file)
        tmp.flush()
        file.seek(0)

        command = 'ffprobe -loglevel error -print_format json -show_format -show_streams'.split()
        command.append(tmp.name)
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


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.

    The minimum version of FFmpeg required is v0.9.
    """

    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): 'video/x-matroska',
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): 'video/quicktime',
        ('yuv4mpegpipe', 'video'): 'video/x-yuv4mpegpipe',
        ('mp3', 'audio'): 'audio/mpeg',
        ('ogg', 'audio'): 'audio/ogg',
        ('wav', 'audio'): 'audio/wav',
    }

    __mime_type_to_encoder = {
        'video/x-matroska': 'matroska',
        'video/quicktime': 'mov',
        'video/x-yuv4mpegpipe': 'yuv4mpegpipe',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
        'audio/wav': 'wav',
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

    def _can_read(self, file):
        try:
            probe_data = _probe(file)
            return bool(probe_data)
        except CalledProcessError:
            return False

    def _read(self, file):
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

        return Asset(essence=file, **metadata)

    @operator
    def resize(self, asset, width, height):
        if width < 1 or height < 1:
            raise ValueError('Invalid dimensions: %dx%d' % (width, height))

        try:
            encoder_name = self.__mime_type_to_encoder[asset.mime_type]
        except KeyError:
            raise UnsupportedFormatError('Unsupported asset type: %s' % asset.mime_type)
        if asset.mime_type.split('/')[0] not in ('image', 'video'):
            raise OperatorError('Cannot resize asset of type %s')

        with tempfile.NamedTemporaryFile() as tmp:
            command = ['ffmpeg', '-loglevel', 'error', '-f', encoder_name, '-i', 'pipe:',
                       '-filter:v', 'scale=%d:%d' % (width, height),
                       '-f', encoder_name, '-y', tmp.name]

            try:
                subprocess_run(command, input=asset.essence.read(),
                               stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not resize video asset: %s' % error_message)

            return Asset(essence=tmp, width=width, height=height)

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
        ffmpeg_type = self.__mime_type_to_encoder[mime_type]

        command = ['ffmpeg', '-loglevel', 'error', '-i', 'pipe:']
        if video is not None:
            if 'codec' in video: command.extend(['-c:v', video['codec']])
            if 'bitrate' in video: command.extend(['-b:v', '%dk' % video['bitrate']])
        if audio is not None:
            if 'codec' in audio: command.extend(['-c:a', audio['codec']])
            if 'bitrate' in audio: command.extend(['-b:a', '%dk' % audio['bitrate']])
        if subtitles is not None:
            if 'codec' in subtitles: command.extend(['-c:s', subtitles['codec']])
        with tempfile.NamedTemporaryFile() as tmp:
            command.extend(['-f', ffmpeg_type, '-y', tmp.name])

            try:
                subprocess_run(command, input=asset.essence.read(),
                               stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not convert video asset: %s' % error_message)

            return Asset(essence=tmp, mime_type=mime_type)


class FFmpegMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor that uses FFmpeg.
    """
    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): 'video/x-matroska',
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): 'video/quicktime',
        ('mp3', 'audio'): 'audio/mpeg',
        ('ogg', 'audio'): 'audio/ogg',
        ('wav', 'audio'): 'audio/wav',
    }

    __mime_type_to_encoder = {
        'video/x-matroska': 'matroska',
        'video/quicktime': 'mov',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
        'audio/wav': 'wav',
    }

    # See https://wiki.multimedia.cx/index.php?title=FFmpeg_Metadata
    __metadata_keys_by_mime_type = {
        'video/x-matroska': bidict({}),
        'video/quicktime': bidict({}),
        'video/x-yuv4mpegpipe': bidict({}),
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
        metadata_keys = self.__metadata_keys_by_mime_type[mime_type]
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
        with tempfile.NamedTemporaryFile() as tmp:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error', '-f', encoder_name, '-i', 'pipe:',
                       '-map_metadata', '-1', '-codec', 'copy', '-y', '-f', encoder_name, tmp.name]
            try:
                subprocess_run(command, input=file.read(),
                               stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not strip metadata: %s' % error_message)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result

    @staticmethod
    def __copy_bytes(file):
        clone = io.BytesIO()
        shutil.copyfileobj(file, clone)
        return clone

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
        with tempfile.NamedTemporaryFile() as tmp:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error', '-f', encoder_name, '-i', 'pipe:']

            ffmetadata = metadata_by_type['ffmetadata']
            metadata_keys = self.__metadata_keys_by_mime_type[mime_type]
            for metadata_key, value in ffmetadata.items():
                ffmetadata_key = metadata_keys.get(metadata_key)
                if ffmetadata_key is None:
                    raise ValueError('Unsupported metadata key: %r' % metadata_key)
                command.append('-metadata')
                command.append('%s=%s' % (ffmetadata_key, value))

            command.extend(['-codec', 'copy', '-y', '-f', encoder_name, tmp.name])

            try:
                subprocess_run(command, input=file.read(),
                               stderr=subprocess.PIPE, check=True)
            except CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not add metadata: %s' % error_message)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result
