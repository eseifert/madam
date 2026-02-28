"""Tests for FileSystemAssetStorage."""
import io

import pytest

from madam.core import Asset, FileSystemAssetStorage


@pytest.fixture
def storage_path(tmp_path):
    return tmp_path / 'assets'


@pytest.fixture
def storage(storage_path):
    return FileSystemAssetStorage(storage_path)


@pytest.fixture
def sample_asset():
    return Asset(io.BytesIO(b'hello world'), mime_type='text/plain')


class TestFileSystemAssetStorage:
    def test_storage_directory_is_created_on_init(self, storage_path):
        FileSystemAssetStorage(storage_path)
        assert storage_path.is_dir()

    def test_store_and_retrieve_asset(self, storage, sample_asset):
        storage['key1'] = sample_asset, set()
        retrieved_asset, _ = storage['key1']
        assert retrieved_asset.essence.read() == sample_asset.essence.read()

    def test_retrieved_asset_has_original_metadata(self, storage, sample_asset):
        storage['key1'] = sample_asset, set()
        retrieved_asset, _ = storage['key1']
        assert retrieved_asset.mime_type == sample_asset.mime_type

    def test_tags_are_stored_and_retrieved(self, storage, sample_asset):
        storage['key1'] = sample_asset, {'portrait', 'raw'}
        _, tags = storage['key1']
        assert tags == frozenset({'portrait', 'raw'})

    def test_key_error_on_missing_key(self, storage):
        with pytest.raises(KeyError):
            _ = storage['nonexistent']

    def test_contains_returns_false_for_missing_key(self, storage):
        assert 'nonexistent' not in storage

    def test_contains_returns_true_after_store(self, storage, sample_asset):
        storage['key1'] = sample_asset, set()
        assert 'key1' in storage

    def test_delete_removes_asset(self, storage, sample_asset):
        storage['key1'] = sample_asset, set()
        del storage['key1']
        assert 'key1' not in storage

    def test_delete_raises_key_error_for_missing(self, storage):
        with pytest.raises(KeyError):
            del storage['nonexistent']

    def test_len_reflects_stored_count(self, storage, sample_asset):
        assert len(storage) == 0
        storage['k1'] = sample_asset, set()
        storage['k2'] = Asset(io.BytesIO(b'other'), mime_type='text/plain'), set()
        assert len(storage) == 2

    def test_iter_yields_all_keys(self, storage):
        keys = ['a', 'b', 'c']
        for k in keys:
            storage[k] = Asset(io.BytesIO(k.encode()), mime_type='text/plain'), set()
        assert set(storage) == set(keys)

    def test_data_persists_across_new_storage_instance(self, storage_path, sample_asset):
        storage1 = FileSystemAssetStorage(storage_path)
        storage1['persistent'] = sample_asset, {'tag1'}

        storage2 = FileSystemAssetStorage(storage_path)
        retrieved, tags = storage2['persistent']
        assert retrieved.essence.read() == sample_asset.essence.read()
        assert tags == frozenset({'tag1'})

    def test_filter_by_tags_works(self, storage):
        a1 = Asset(io.BytesIO(b'a1'), mime_type='text/plain')
        a2 = Asset(io.BytesIO(b'a2'), mime_type='text/plain')
        storage['k1'] = a1, {'foo', 'bar'}
        storage['k2'] = a2, {'foo'}

        result = set(storage.filter_by_tags('bar'))
        assert 'k1' in result
        assert 'k2' not in result

    def test_filter_by_metadata_works(self, storage):
        a = Asset(io.BytesIO(b'img'), mime_type='image/jpeg', width=1920)
        storage['img'] = a, set()
        assert 'img' in storage.filter(width=1920)
        assert 'img' not in storage.filter(width=800)
