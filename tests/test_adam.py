import pytest

from adam.adam import *

def test_contains_asset():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    assert storage['key'] == a
    
def test_contains_key():
    storage = AssetStorage()
    a = Asset()
    assert 'key' not in storage
    storage['key'] = a
    assert 'key' in storage
    
def test_asset_is_versioned():
    storage = AssetStorage()
    a = Asset()
    updated_a = Asset()
    storage['key'] = a
    storage['key'] = updated_a
    versions = storage.versions_of('key')
    assert len(versions) == 2
    assert versions[0] == a
    assert versions[1] == updated_a

def test_asset_is_deleted():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    del storage['key']
    assert 'key' not in storage

def test_deleting_unkown_key_raises_exception():
    storage = AssetStorage()
    with pytest.raises(KeyError):
        del storage['key']

def test_create_asset_from_wav():
    reader = WavReader()
    asset = reader.read('tests/16-bit-mono.wav')
    assert asset.mime_type == 'audio/wav'
    assert asset.framerate == 48000
    assert asset.channels == 1
    assert asset.essence != None