import adam


def test_create_asset_from_wav():
    asset = adam.read_wav('tests/16-bit-mono.wav')
    assert asset['mime_type'] == 'audio/wav'
    assert asset['framerate'] == 48000
    assert asset['channels'] == 1
    assert asset.essence is not None


def test_create_asset_from_mp3():
    mp3_file_path = 'tests/64kbits.mp3'
    with open(mp3_file_path, 'rb') as mp3_file:
        asset = adam.read_mp3(mp3_file)
    assert asset['mime_type'] == 'audio/mpeg'
    assert asset['duration'] == 0.1
    assert asset.essence is not None

    # Assert that essence was stripped from metadata
    with open(mp3_file_path, 'rb') as mp3_file:
        assert asset.essence != mp3_file.read()


def test_mp3_reader_does_not_change_file():
    mp3_file_path = 'tests/64kbits.mp3'
    with open(mp3_file_path, 'rb') as mp3_file:
        expected_data = mp3_file.read()
    with open(mp3_file_path, 'rb') as mp3_file:
        adam.read_mp3(mp3_file)
    with open(mp3_file_path, 'rb') as mp3_file:
        actual_data = mp3_file.read()
    assert expected_data == actual_data
