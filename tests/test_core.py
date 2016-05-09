import pytest
import tempfile

import adam
from adam.core import AssetStorage
from adam.core import Asset
from adam.core import UnknownMimeTypeError


@pytest.fixture
def storage():
    return AssetStorage()


def test_contains_asset(storage):
    a = Asset()
    storage['key'] = a
    assert storage['key'] == a
    

def test_contains_key(storage):
    a = Asset()
    assert 'key' not in storage
    storage['key'] = a
    assert 'key' in storage
    

def test_asset_is_versioned(storage):
    a = Asset()
    updated_a = Asset()
    storage['key'] = a
    storage['key'] = updated_a
    versions = storage.versions_of('key')
    assert len(versions) == 2
    assert versions[0] == a
    assert versions[1] == updated_a


def test_asset_is_deleted(storage):
    a = Asset()
    storage['key'] = a
    del storage['key']
    assert 'key' not in storage


def test_get_returns_empty_list_when_storage_is_empty(storage):
    assets_with_1s_duration = storage.get()
    assert not assets_with_1s_duration
    

def test_get_returns_assets_with_specified_adam_metadata(storage):
    a = Asset()
    a['duration'] = 1
    storage['key'] = a

    assets_with_1s_duration = storage.get(duration=1)

    assert len(assets_with_1s_duration) == 1
    assert assets_with_1s_duration[0] == a


def test_read_unkown_file():
    wav_path = 'tests/16-bit-mono.wav'
    asset = adam.read(wav_path)
    assert asset == adam.read_wav(wav_path)

    mp3_path = 'tests/64kbits.mp3'
    asset = adam.read(mp3_path)
    with open(mp3_path, 'rb') as mp3_file:
        assert asset == adam.read_mp3(mp3_file)
    

def test_reading_file_with_unknown_mime_type_raises_exception():
    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(UnknownMimeTypeError):
            adam.read(tmp.name)


def test_supported_mime_types():
    assert len(adam.supported_mime_types) > 0


def test_deleting_unkown_key_raises_exception(storage):
    with pytest.raises(KeyError):
        del storage['key']


def test_asset_has_mime_type():
    a = Asset()
    assert hasattr(a, 'mime_type')


def test_asset_has_essence():
    asset = Asset()
    assert hasattr(asset, 'essence')


def test_asset_has_metadata_dict():
    asset = Asset()
    assert asset.metadata == {'adam': {}}


def test_asset_equality():
    a = Asset()
    a.some_attr = 42
    b = Asset()
    b.some_attr = 42
    
    assert a is not b
    assert a == b


def test_asset_getitem_is_identical_to_access_through_adam_metadata():
    asset = Asset()
    adam_metadata = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}
    asset.metadata['adam'] = adam_metadata

    for key, value in asset.metadata['adam'].items():
        assert asset[key] == value


def test_asset_setitem_is_identical_to_access_through_adam_metadata():
    asset = Asset()
    metadata_to_be_set = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}

    for key, value in metadata_to_be_set.items():
        asset[key] = value

    assert asset.metadata['adam'] == metadata_to_be_set
