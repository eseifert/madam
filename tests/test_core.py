import pytest
import tempfile
import unittest.mock

import adam
from adam.core import AssetStorage
from adam.core import Asset
from adam.core import UnknownMimeTypeError
from adam.core import Pipeline


@pytest.fixture
def storage():
    return AssetStorage()


@pytest.mark.usefixtures('storage')
class TestAssetStorage:
    def test_contains_asset(self, storage):
        a = Asset()
        storage['key'] = a
        assert storage['key'] == a

    def test_contains_key(self, storage):
        a = Asset()
        assert 'key' not in storage
        storage['key'] = a
        assert 'key' in storage

    def test_asset_is_versioned(self, storage):
        a = Asset()
        updated_a = Asset()
        storage['key'] = a
        storage['key'] = updated_a
        versions = storage.versions_of('key')
        assert len(versions) == 2
        assert versions[0] == a
        assert versions[1] == updated_a

    def test_asset_is_deleted(self, storage):
        a = Asset()
        storage['key'] = a
        del storage['key']
        assert 'key' not in storage

    def test_deleting_unknown_key_raises_exception(self, storage):
        with pytest.raises(KeyError):
            del storage['key']

    def test_get_returns_empty_list_when_storage_is_empty(self, storage):
        assets_with_1s_duration = storage.get()
        assert not assets_with_1s_duration

    def test_get_returns_assets_with_specified_adam_metadata(self, storage):
        a = Asset()
        a['duration'] = 1
        storage['key'] = a

        assets_with_1s_duration = storage.get(duration=1)

        assert len(assets_with_1s_duration) == 1
        assert assets_with_1s_duration[0] == a


@pytest.fixture
def asset():
    return Asset()


@pytest.mark.usefixtures('asset')
class TestAsset:
    def test_asset_has_mime_type(self, asset):
        assert hasattr(asset, 'mime_type')

    def test_asset_has_essence(self, asset):
        assert hasattr(asset, 'essence')

    def test_asset_has_metadata_dict(self, asset):
        assert asset.metadata == {'adam': {}}

    def test_asset_equality(self, asset):
        asset.some_attr = 42
        another_asset = Asset()
        another_asset.some_attr = 42

        assert asset is not another_asset
        assert asset == another_asset

    def test_asset_getitem_is_identical_to_access_through_adam_metadata(self, asset):
        adam_metadata = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}
        asset.metadata['adam'] = adam_metadata

        for key, value in asset.metadata['adam'].items():
            assert asset[key] == value

    def test_asset_setitem_is_identical_to_access_through_adam_metadata(self, asset):
        metadata_to_be_set = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}

        for key, value in metadata_to_be_set.items():
            asset[key] = value

        assert asset.metadata['adam'] == metadata_to_be_set


@pytest.mark.parametrize('file_path,read_method_to_be_mocked', [
    ('tests/16-bit-mono.wav', adam.read_wav),
    ('tests/64kbits.mp3', adam.read_mp3)
])
def test_read_calls_read_method_for_respective_file_type(file_path, read_method_to_be_mocked):
    mocked_read_method = unittest.mock.MagicMock()
    for mime_type, read_method in adam.read_method_by_mime_type.items():
        if read_method == read_method_to_be_mocked:
            adam.read_method_by_mime_type[mime_type] = mocked_read_method

    adam.read(file_path)

    assert mocked_read_method.called


def test_reading_file_with_unknown_mime_type_raises_exception():
    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(UnknownMimeTypeError):
            adam.read(tmp.name)


def test_supported_mime_types():
    assert len(adam.supported_mime_types) > 0


@pytest.fixture
def pipeline():
    return Pipeline()


def test_empty_pipeline_does_not_change_assets(pipeline, asset):
    another_asset = Asset()

    processed_assets = pipeline.process(asset, another_asset)

    assert asset in processed_assets
    assert another_asset in processed_assets


def test_pipeline_contains_operator_after_it_was_added(pipeline, asset):
    operator = unittest.mock.MagicMock()

    pipeline.add(operator)

    assert operator in pipeline.operators
