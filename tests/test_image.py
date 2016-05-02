import adam.image
import tempfile
import PIL.Image

def test_supports_jfif():
    assert 'image/jpeg' in adam.supported_mime_types
    
def test_read_jpeg_returns_asset_with_jpeg_mime_type():
    # Given
    empty_image = PIL.Image.new('RGB', (1, 1))
    with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp:
        jpeg_file = empty_image.save(tmp.name, 'JPEG')
        # When
        jpeg_asset = adam.image.readJpeg(tmp.name)
    # Then
    assert jpeg_asset.mime_type =='image/jpeg'

def test_jpeg_asset_essence_is_filled():
    # Given
    empty_image = PIL.Image.new('RGB', (1, 1))
    with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp:
        jpeg_file = empty_image.save(tmp.name, 'JPEG')
        # When
        jpeg_asset = adam.image.readJpeg(tmp.name)
    # Then
    assert jpeg_asset.essence != None

