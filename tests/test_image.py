import adam.image
import io
import PIL.Image

def test_supports_jfif():
    assert 'image/jpeg' in adam.supported_mime_types
    
def test_read_jpeg_returns_asset_with_jpeg_mime_type():
    # Given
    empty_image = PIL.Image.new('RGB', (1, 1))
    image_data = io.BytesIO()
    jpeg_file = empty_image.save(image_data, 'JPEG')
    # When
    jpeg_asset = adam.image.read_jpeg(image_data)
    # Then
    assert jpeg_asset.mime_type =='image/jpeg'

def test_jpeg_asset_essence_is_filled():
    # Given
    empty_image = PIL.Image.new('RGB', (1, 1))
    image_data = io.BytesIO()
    jpeg_file = empty_image.save(image_data, 'JPEG')
    # When
    jpeg_asset = adam.image.read_jpeg(image_data)
    # Then
    assert jpeg_asset.essence != None

