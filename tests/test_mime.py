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
