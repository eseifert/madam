from madam.mime import MimeType


def test_mime_type_stores_strings_or_none():
    mime = MimeType(type='foo', subtype='bar')
    assert mime.type == 'foo'
    assert mime.subtype == 'bar'

    mime = MimeType(type=None, subtype=None)
    assert mime.type is None
    assert mime.subtype is None

    mime = MimeType(type='', subtype='')
    assert mime.type is None
    assert mime.subtype is None


def test_mime_type_handles_wildcards():
    mime = MimeType(type='foo', subtype='*')
    assert mime.type == 'foo'
    assert mime.subtype is None

    mime = MimeType(type='*', subtype='bar')
    assert mime.type is None
    assert mime.subtype == 'bar'

    mime = MimeType(type='*', subtype='*')
    assert mime.type is None
    assert mime.subtype is None


def test_mime_type_can_parse_mime_type_strings():
    mime = MimeType('foo/bar')
    assert mime.type == 'foo' and mime.subtype == 'bar'

    mime = MimeType('foo/*')
    assert mime.type == 'foo' and mime.subtype is None

    mime = MimeType('*/bar')
    assert mime.type is None and mime.subtype == 'bar'

    mime = MimeType('*/*')
    assert mime.type is None and mime.subtype is None


def test_mime_type_returns_correct_mime_type_string():
    mime = MimeType(type='foo', subtype='bar')
    assert str(mime) == 'foo/bar'

    mime = MimeType(type='foo', subtype=None)
    assert str(mime) == 'foo/*'

    mime = MimeType(type=None, subtype='bar')
    assert str(mime) == '*/bar'

    mime = MimeType(type=None, subtype=None)
    assert str(mime) == '*/*'


def test_mime_type_returns_valid_hash_code():
    mime = MimeType(type='foo', subtype='bar')
    assert hash(mime) == hash(('foo', 'bar'))


def test_mime_can_be_checked_for_equality_with_another_mime_type():
    mime1 = MimeType(type='foo', subtype='bar')
    mime2 = MimeType(type=None, subtype=None)
    assert mime1 == mime1
    assert mime2 == mime2

    mime3 = MimeType(type='foo', subtype='baz')
    assert not (mime1 == mime3)
    assert not (mime2 == mime3)

    mime4 = MimeType(type='foo', subtype=None)
    assert not (mime1 == mime4)
    assert not (mime2 == mime4)
