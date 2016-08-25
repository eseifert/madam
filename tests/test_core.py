import unittest.mock

import os
import pytest
import tempfile

from madam.core import Asset
from madam.core import InMemoryStorage, FileStorage
from madam.core import Pipeline


@pytest.fixture
def in_memory_storage():
    return InMemoryStorage()


@pytest.fixture
def file_storage(tmpdir):
    storage_path = str(tmpdir.join('storageDir'))
    return FileStorage(storage_path)


@pytest.mark.usefixtures('asset', 'in_memory_storage', 'file_storage')
class TestStorages:
    @pytest.fixture(params=['in_memory_storage', 'file_storage'])
    def storage(self, request, in_memory_storage, file_storage):
        if request.param == 'in_memory_storage':
            return in_memory_storage
        elif request.param == 'file_storage':
            return file_storage

    def test_contains_is_false_when_storage_is_empty(self, storage, asset):
        contains = asset in storage

        assert not contains

    def test_contains_is_true_when_asset_was_added(self, storage, asset):
        storage.add(asset)

        assert asset in storage

    def test_contains_is_false_when_asset_was_deleted(self, storage, asset):
        storage.add(asset)

        storage.remove(asset)

        assert asset not in storage

    def test_remove_raises_value_error_when_deleting_unknown_asset(self, storage, asset):
        with pytest.raises(ValueError):
            storage.remove(asset)

    def test_remove_deletes_asset_from_storage(self, storage, asset):
        storage.add(asset)

        storage.remove(asset)

        assert asset not in storage

    def test_iterator_contains_all_stored_assets(self, storage):
        storage.add(Asset(b'0', metadata={}))
        storage.add(Asset(b'1', metadata={}))
        storage.add(Asset(b'2', metadata={}))

        iterator = iter(storage)

        assert len(list(iterator)) == 3

    def test_iterator_is_a_readable_storage_snapshot(self, storage):
        asset0 = Asset(b'0', metadata={})
        asset1 = Asset(b'1', metadata={})
        storage.add(asset0)
        storage.add(asset1)
        iterator = iter(storage)

        storage.remove(asset0)
        storage.add(Asset(b'2', metadata={}))
        storage.add(Asset(b'3', metadata={}))

        assert set(iterator) == {asset0, asset1}

    def test_filter_by_tags_returns_empty_iterator_when_storage_is_empty(self, storage):
        tagged_assets = storage.filter_by_tags('some tag')

        assert len(list(tagged_assets)) == 0

    def test_filter_by_tags_returns_all_assets_when_no_tags_are_specified(self, storage):
        asset = Asset(b'TestEssence', metadata={})
        storage.add(asset, tags={'foo'})

        assets = storage.filter_by_tags()

        assert asset in assets

    def test_filter_by_tags_returns_assets_with_specified_tags(self, storage):
        asset0 = Asset(b'0', metadata={})
        asset1 = Asset(b'1', metadata={})
        asset2 = Asset(b'2', metadata={})
        storage.add(asset0, tags={'foo'})
        storage.add(asset1, tags={'foo', 'bar'})
        storage.add(asset2, tags={'foo', 'bar'})

        assets = list(storage.filter_by_tags('bar', 'foo'))

        assert asset0 not in assets and asset1 in assets and asset2 in assets

    @pytest.mark.parametrize('tags', [None, {'my', 'tags'}])
    def test_add_does_nothing_when_asset_is_already_in_storage(self, storage, asset, tags):
        storage.add(asset, tags=tags)

        storage.add(asset, tags=tags)

        assert len(list(storage)) == 1


@pytest.mark.usefixtures('asset', 'file_storage')
class TestFileStorage:
    @pytest.fixture
    def storage(self, file_storage):
        return file_storage

    def test_creates_storage_directory(self, storage):
        assert os.path.isdir(storage.path)

    def test_uses_directory_when_directory_already_exists(self):
        with tempfile.TemporaryDirectory() as tempdir:
            storage_path = os.path.join(tempdir, 'storageDir')
            os.mkdir(storage_path)

            FileStorage(storage_path)

    def test_raises_error_when_storage_path_is_a_file(self):
        with tempfile.NamedTemporaryFile() as file:
            with pytest.raises(FileExistsError):
                FileStorage(file.name)

    def test_add_writes_data_to_storage_path(self, storage, asset):
        storage.add(asset)

        storage_path_file_count = len(os.listdir(storage.path))
        assert storage_path_file_count >= 1


@pytest.mark.usefixtures('in_memory_storage')
class TestInMemoryStorage:
    @pytest.fixture
    def storage(self, in_memory_storage):
        return in_memory_storage

    def test_get_returns_empty_list_when_storage_is_empty(self, storage):
        assets_with_1s_duration = storage.get()
        assert not assets_with_1s_duration

    def test_get_returns_assets_with_specified_madam_metadata(self, storage):
        asset = Asset(b'TestEssence', metadata={'duration': 1})
        storage.add(asset)

        assets_with_1s_duration = storage.get(duration=1)

        assert len(assets_with_1s_duration) == 1
        assert assets_with_1s_duration[0] == asset


@pytest.fixture
def asset():
    return Asset(b'TestEssence', metadata={})


@pytest.mark.usefixtures('asset')
class TestAsset:
    def test_asset_has_mime_type(self, asset):
        assert hasattr(asset, 'mime_type')

    def test_asset_has_essence(self, asset):
        assert hasattr(asset, 'essence')

    def test_asset_has_metadata(self, asset):
        assert hasattr(asset, 'metadata')

    def test_assets_are_equal_when_essence_and_properties_are_identical(self, asset):
        asset.some_attr = 42
        another_asset = Asset(asset.essence.read(), metadata={})
        another_asset.some_attr = 42

        assert asset is not another_asset
        assert asset == another_asset

    def test_asset_getattr_is_identical_to_access_through_metadata(self):
        asset = Asset(b'TestEssence', metadata={'SomeKey': 'SomeValue', 'AnotherKey': None, '42': 43.0})

        for key, value in asset.metadata.items():
            assert getattr(asset, key) == value

    def test_setattr_raises_when_attribute_is_a_metadata_attribute(self):
        asset_with_metadata = Asset(b'', metadata={'SomeMetadata': 42})

        with pytest.raises(NotImplementedError):
            asset_with_metadata.SomeMetadata = 43


    def test_asset_essence_can_be_read_multiple_times(self, asset):
        essence_contents = asset.essence.read()
        same_essence_contents = asset.essence.read()

        assert essence_contents == same_essence_contents

    def test_hash_is_equal_for_equal_assets(self):
        metadata = {'SomeMetadata': 42}
        asset0 = Asset(b'same', metadata)
        asset1 = Asset(b'same', metadata)

        assert hash(asset0) == hash(asset1)

    def test_hash_is_different_when_assets_have_different_metadata(self):
        asset0 = Asset(b'same', metadata={'SomeMetadata': 42})
        asset1 = Asset(b'same', metadata={'DifferentMetadata': 43})

        assert hash(asset0) != hash(asset1)


@pytest.mark.usefixtures('asset')
class TestPipeline:
    @pytest.fixture
    def pipeline(self):
        return Pipeline()

    def test_empty_pipeline_does_not_change_assets(self, pipeline, asset):
        another_asset = Asset(b'other', metadata={})

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
