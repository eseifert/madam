import pytest

from madam.mime import MimeType


def test_mime_type_accepts_mime_type_instance_in_constructor():
    template = MimeType(mediatype='foo', subtype='bar')
    mime = MimeType(template)
    assert mime.type == 'foo'
    assert mime.subtype == 'bar'


def test_mime_type_accepts_strings_in_constructor():
    mime = MimeType(mediatype='foo', subtype='bar')
    assert mime.type == 'foo'
    assert mime.subtype == 'bar'

    mime = MimeType(mediatype='', subtype='')
    assert mime.type is None
    assert mime.subtype is None


def test_mime_type_accepts_none_in_constructor():
    mime = MimeType(mediatype=None, subtype=None)
    assert mime.type is None
    assert mime.subtype is None


def test_mime_type_cannot_be_initialized_with_anything_but_string_or_none():
    with pytest.raises(TypeError):
        MimeType(mediatype=42, subtype='bar')


def test_mime_type_cannot_be_initialized_with_mime_type_string_and_subtype_string():
    with pytest.raises(ValueError):
        MimeType(mediatype='foo/bar', subtype='baz')


def test_mime_type_type_cannot_contain_more_than_one_delimiter():
    with pytest.raises(ValueError):
        MimeType('foo/bar/baz')


def test_mime_type_subtype_cannot_contain_a_delimiter():
    with pytest.raises(ValueError):
        MimeType(mediatype='foo', subtype='bar/baz')


def test_mime_type_handles_wildcards():
    mime = MimeType(mediatype='foo', subtype='*')
    assert mime.type == 'foo'
    assert mime.subtype is None

    mime = MimeType(mediatype='*', subtype='bar')
    assert mime.type is None
    assert mime.subtype == 'bar'

    mime = MimeType(mediatype='*', subtype='*')
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


def test_mime_type_has_string_representation():
    mime = MimeType(mediatype='foo', subtype=None)
    assert repr(mime) == "MimeType(mediatype='foo', subtype=None)"


def test_mime_type_returns_correct_mime_type_string():
    mime = MimeType(mediatype='foo', subtype='bar')
    assert str(mime) == 'foo/bar'

    mime = MimeType(mediatype='foo', subtype=None)
    assert str(mime) == 'foo/*'

    mime = MimeType(mediatype=None, subtype='bar')
    assert str(mime) == '*/bar'

    mime = MimeType(mediatype=None, subtype=None)
    assert str(mime) == '*/*'


def test_mime_type_returns_valid_hash_code():
    mime = MimeType(mediatype='foo', subtype='bar')
    assert hash(mime) == hash('foo/bar')

    mime = MimeType(mediatype='foo', subtype=None)
    assert hash(mime) == hash('foo/*')


def test_mime_type_can_be_checked_for_equality_with_another_mime_type():
    mime1 = MimeType(mediatype='foo', subtype='bar')
    mime2 = MimeType(mediatype=None, subtype=None)
    assert mime1 == mime1
    assert mime2 == mime2

    mime3 = MimeType(mediatype='foo', subtype='baz')
    assert not (mime1 == mime3)
    assert not (mime2 == mime3)

    mime4 = MimeType(mediatype='foo', subtype=None)
    assert not (mime1 == mime4)
    assert not (mime2 == mime4)


def test_mime_type_is_case_insensitive():
    mime1 = MimeType(mediatype='foo', subtype='bar')

    mime2 = MimeType(mediatype='fOo', subtype='bAr')
    assert mime1 == mime2

    mime3 = MimeType(mediatype='Foo', subtype='baR')
    assert mime1 == mime3


def test_mime_type_can_be_equal_to_a_mime_type_string():
    mime = MimeType(mediatype='foo', subtype='bar')
    assert mime == 'foo/bar'

    mime = MimeType(mediatype='foo', subtype=None)
    assert mime == 'foo/*'

    mime = MimeType(mediatype=None, subtype='bar')
    assert mime == '*/bar'

    mime = MimeType(mediatype=None, subtype=None)
    assert mime == '*/*'


def test_mime_type_has_a_total_ordering():
    mime1 = MimeType(mediatype='foo', subtype='bar')
    mime2 = MimeType(mediatype='foo', subtype='baz')
    assert mime1 < mime2
    assert mime2 > mime1

    mime3 = MimeType(mediatype='foo', subtype=None)
    assert mime3 < mime1

    mime4 = MimeType(mediatype=None, subtype='bar')
    assert mime4 < mime2
