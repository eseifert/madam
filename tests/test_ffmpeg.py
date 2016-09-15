import pytest

from ffmpeg import FFMetadataParser


class TestFFMetadataParser:
    @pytest.fixture(name='parser')
    def ffmetadata_parser(self):
        return FFMetadataParser()

    def test_can_parse_empty_content(self, parser):
        data = ';FFMETADATA1'

        metadata = parser.read_string(data)

        assert FFMetadataParser.GLOBAL_SECTION in metadata

    def test_fails_for_content_with_invalid_header(self, parser):
        data = ';INVALIDFORMAT'

        with pytest.raises(ValueError):
            parser.read_string(data)

    def test_fails_for_content_with_invalid_version(self, parser):
        data = ';FFMETADATA0'

        with pytest.raises(ValueError):
            parser.read_string(data)

    def test_fails_when_parsing_invalid_content(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            'invalid content'
        ])

        with pytest.raises(ValueError):
            parser.read_string(data)

    def test_can_parse_comments(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            '',
            ';this is a comment',
            '#chapter ends at 0:01:00'
        ])

        metadata = parser.read_string(data)

        global_section = metadata[FFMetadataParser.GLOBAL_SECTION]
        assert not global_section

    def test_can_parse_key_value_pairs(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            'key=value',
            'key = value'
        ])

        metadata = parser.read_string(data)

        global_section = metadata[FFMetadataParser.GLOBAL_SECTION]
        assert global_section['key'] == 'value'
        assert global_section['key '] == ' value'

    def test_can_parse_escaped_characters(self, parser):
        # Test data from https://www.ffmpeg.org/ffmpeg-formats.html
        data = '\n'.join([
            ';FFMETADATA1',
            # equals sign
            'equal=escaped\\=value',
            'equal\\=escaped=key',
            # semicolon
            'semicolon=escaped\\;value',
            'semicolon\\;escaped=key',
            # hash sign
            'hash=escaped\\#value',
            'hash\\#escaped=key',
            # backslash
            'backslash=escaped\\\\value',
            'backslash\\\\escaped=key',
            # escaped newlines
            'multi=line\\', ' value',
            'multi\\', 'line=key'
        ])

        metadata = parser.read_string(data)

        global_section = metadata[FFMetadataParser.GLOBAL_SECTION]
        assert global_section['equal'] == 'escaped=value'
        assert global_section['semicolon'] == 'escaped;value'
        assert global_section['hash'] == 'escaped#value'
        assert global_section['backslash'] == 'escaped\\value'
        assert global_section['equal=escaped'] == 'key'
        assert global_section['semicolon;escaped'] == 'key'
        assert global_section['hash#escaped'] == 'key'
        assert global_section['backslash\\escaped'] == 'key'
        assert global_section['multi'] == 'line value'
        assert global_section['multiline'] == 'key'

    def test_fails_with_missing_escaping(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            'unescaped=equals=sign',
            'unescaped;semi=colon;',
            'unescaped#hash=sign'
        ])

        with pytest.raises(ValueError):
            parser.read_string(data)

    def test_fails_with_illegal_escaping(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            '\invalid=\escaping'
        ])

        with pytest.raises(ValueError):
            parser.read_string(data)

    def test_can_parse_sections(self, parser):
        data = '\n'.join([
            ';FFMETADATA1',
            'key 1=global value 1',
            'key 2=global value 2',
            '[CHAPTER]',
            'key 1=chapter value 1',
            'key 2=chapter value 2',
            '[STREAM]',
            'key 1=stream value 1',
            'key 2=stream value 2',
        ])

        metadata = parser.read_string(data)

        global_section = metadata[FFMetadataParser.GLOBAL_SECTION]
        assert global_section['key 1'] == 'global value 1'
        assert global_section['key 2'] == 'global value 2'
        chapter = metadata['CHAPTER']
        assert chapter['key 1'] == 'chapter value 1'
        assert chapter['key 2'] == 'chapter value 2'
        stream = metadata['STREAM']
        assert stream['key 1'] == 'stream value 1'
        assert stream['key 2'] == 'stream value 2'
