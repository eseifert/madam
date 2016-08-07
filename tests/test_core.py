import io
import os
import pytest
import tempfile
import unittest.mock

import madam
from madam.core import AssetStorage, FileStorage
from madam.core import Asset
from madam.core import UnsupportedFormatError
from madam.core import Pipeline


def test_file_storage_creates_storage_directory():
    with tempfile.TemporaryDirectory() as tempdir:
        storagePath = os.path.join(tempdir, 'storageDir')

        storage = FileStorage(storagePath)

        assert os.path.isdir(storagePath)


def test_file_storage_uses_directory_when_directory_already_exists():
    with tempfile.TemporaryDirectory() as tempdir:
        storagePath = os.path.join(tempdir, 'storageDir')
        os.mkdir(storagePath)

        storage = FileStorage(storagePath)


class TestAssetStorage:
    @pytest.fixture
    def storage(self):
        return AssetStorage()

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

    def test_get_returns_assets_with_specified_madam_metadata(self, storage):
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
        assert asset.metadata == {'madam': {}}

    def test_asset_equality(self, asset):
        asset.some_attr = 42
        another_asset = Asset()
        another_asset.some_attr = 42

        assert asset is not another_asset
        assert asset == another_asset

    def test_asset_getitem_is_identical_to_access_through_madam_metadata(self, asset):
        madam_metadata = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}
        asset.metadata['madam'] = madam_metadata

        for key, value in asset.metadata['madam'].items():
            assert asset[key] == value

    def test_asset_setitem_is_identical_to_access_through_madam_metadata(self, asset):
        metadata_to_be_set = {'SomeKey': 'SomeValue', 'AnotherKey': None, 42: 43.0}

        for key, value in metadata_to_be_set.items():
            asset[key] = value

        assert asset.metadata['madam'] == metadata_to_be_set

    def test_asset_essence_can_be_read_multiple_times(self, asset):
        asset.essence_data = b'42'
        essence_contents = asset.essence.read()
        same_essence_contents = asset.essence.read()

        assert essence_contents == same_essence_contents


@pytest.mark.parametrize('path, mime_type', [
    ('tests/16-bit-mono.wav', None),
    ('tests/64kbits.mp3', None),
])
def test_read_calls_read_method_for_respective_file_type(path, mime_type):
    # When
    with open(path, 'rb') as file:
        data = file.read()
    for processor in madam.core.processors:
        if processor.can_read(io.BytesIO(data)):
            with unittest.mock.patch.object(processor, 'read') as read_method:
                # Then
                madam.read(io.BytesIO(data), mime_type=mime_type)
            # Assert
            assert read_method.called
            break


def test_read_empty_file_raises_error():
    file_data = io.BytesIO()
    with pytest.raises(UnsupportedFormatError):
        madam.read(file_data)


@pytest.fixture
def pipeline():
    return Pipeline()


@pytest.mark.usefixtures('asset', 'pipeline')
class TestPipeline:
    def test_empty_pipeline_does_not_change_assets(self, pipeline, asset):
        another_asset = Asset()

        processed_assets = pipeline.process(asset, another_asset)

        assert asset in processed_assets
        assert another_asset in processed_assets

    def test_pipeline_contains_operator_after_it_was_added(self, pipeline):
        operator = unittest.mock.MagicMock()

        pipeline.add(operator)

        assert operator in pipeline.operators

    def test_operator_is_applied_to_assets_when_process_is_called(self, pipeline, asset):
        operator = unittest.mock.MagicMock()
        pipeline.add(operator)

        [processed_asset for processed_asset in pipeline.process(asset)]

        operator.assert_called_once_with(asset)
