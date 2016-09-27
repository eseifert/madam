import datetime
import io
import subprocess

import PIL.Image
import pytest

import madam.core
from madam.future import subprocess_run


def image_rgb(width, height, transpositions=None):
    if not transpositions:
        transpositions = []
    image = PIL.Image.new('RGB', (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    for y in range(0, height):
        for x in range(0, width):
            color = (255, 255, 255) if y == 0 or x == 0 else (0, 0, 0)
            image.putpixel((x, y), color)
    for transposition in transpositions:
        image = image.transpose(transposition)
    return image


def jpeg_rgb(width=4, height=3, transpositions=None):
    if not transpositions:
        transpositions = []
    image = image_rgb(width=width, height=height, transpositions=transpositions)
    image_data = io.BytesIO()
    image.save(image_data, 'JPEG', quality=100)
    image_data.seek(0)
    return image_data


def png_rgb(width, height):
    image = image_rgb(width, height)
    image_data = io.BytesIO()
    image.save(image_data, 'PNG')
    image_data.seek(0)
    return image_data


def gif_rgb(width, height):
    image = image_rgb(width, height)
    image_data = io.BytesIO()
    image.save(image_data, 'GIF')
    image_data.seek(0)
    return image_data


@pytest.fixture(scope='class')
def jpeg_asset(width=4, height=3, transpositions=None, **additional_metadata):
    if not transpositions:
        transpositions = []
    essence = jpeg_rgb(width=width, height=height, transpositions=transpositions)
    metadata = dict(
        exif={'image.artist': 'Test artist'},
        iptc={
            'bylines': ['The', 'Creators'],
            'byline_titles': ['Dr.', 'Prof.'],
            'caption': 'A test image.',
            'contacts': ['Me', 'Myself'],
            'copyright': 'Nobody',
            'creation_date': datetime.date(2000, 1, 1),
            'creation_time': datetime.time(),
            'credit': 'Devs',
            'expiration_date': datetime.date(2000, 1, 1),
            'expiration_time': datetime.time(),
            'headline': 'Wonderful Test Image',
            'image_orientation': 'landscape',
            'keywords': ['test', 'image', 'kws'],
            'language': 'English',
            'release_date': datetime.date(2000, 1, 1),
            'release_time': datetime.time(),
            'source': 'Test suite',
            'subjects': ['The', 'topics'],
        },
        width=width,
        height=height,
        mime_type='image/jpeg'
    )
    metadata.update(additional_metadata)
    asset = madam.core.Asset(essence, **metadata)
    return asset


@pytest.fixture(scope='class')
def png_asset():
    width = 4
    height = 3
    essence = png_rgb(width, height)
    metadata = dict(
        width=width,
        height=height,
        mime_type='image/png'
    )
    asset = madam.core.Asset(essence, **metadata)
    return asset


@pytest.fixture(scope='class')
def gif_asset():
    width = 4
    height = 3
    essence = gif_rgb(width, height)
    metadata = dict(
        width=width,
        height=height,
        mime_type='image/gif'
    )
    asset = madam.core.Asset(essence, **metadata)
    return asset


@pytest.fixture(params=['jpeg_asset', 'png_asset', 'gif_asset'])
def image_asset(request, jpeg_asset, png_asset, gif_asset):
    if request.param == 'jpeg_asset':
        return jpeg_asset
    elif request.param == 'png_asset':
        return png_asset
    else:
        return gif_asset


@pytest.fixture(scope='class')
def wav_asset():
    with open('tests/resources/16-bit-mono.wav', 'rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence),
                            mime_type='audio/wav',
                            duration=0.1)


@pytest.fixture(scope='class')
def mp3_asset():
    with open('tests/resources/64kbits.mp3', 'rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence),
                            mime_type='audio/mpeg',
                            duration=0.144)


@pytest.fixture(scope='class')
def opus_asset():
    with open('tests/resources/sine-440hz-audio.opus', 'rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence),
                            mime_type='audio/ogg',
                            duration=1)


@pytest.fixture(scope='class')
def nut_audio_asset():
    with open('tests/resources/sine-440hz-audio.nut', 'rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence),
                            mime_type='audio/x-nut',
                            duration=1)


@pytest.fixture(params=['mp3_asset', 'opus_asset', 'wav_asset'])
def audio_asset(request, mp3_asset, opus_asset, wav_asset):
    if request.param == 'mp3_asset':
        return mp3_asset
    if request.param == 'opus_asset':
        return opus_asset
    else:
        return wav_asset


@pytest.fixture(scope='class')
def mp4_asset(tmpdir_factory):
    width = 320
    height = 240
    duration = 0.2
    command = ('ffmpeg -loglevel error -f lavfi -i color=color=red:size=%dx%d:duration=%.1f:rate=15 '
               '-c:v libx264 -preset ultrafast -qp 0 -f mp4' % (width, height, duration)).split()
    tmpfile = tmpdir_factory.mktemp('mp4_asset').join('lossless.mp4')
    command.append(str(tmpfile))
    subprocess_run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/quicktime',
                            width=width, height=height, duration=duration)


@pytest.fixture(scope='class')
def y4m_asset():
    width = 320
    height = 240
    duration = 0.2
    command = ('ffmpeg -loglevel error -f lavfi -i color=color=red:size=%dx%d:duration=%.1f:rate=15 '
               '-pix_fmt yuv444p -f yuv4mpegpipe pipe:' % (width, height, duration)).split()
    ffmpeg = subprocess_run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return madam.core.Asset(essence=io.BytesIO(ffmpeg.stdout), mime_type='video/x-yuv4mpegpipe',
                            width=width, height=height, duration=duration)


@pytest.fixture(scope='class', params=['mp4_asset', 'y4m_asset'])
def video_asset(request, mp4_asset, y4m_asset):
    if request.param == 'mp4_asset':
        return mp4_asset
    else:
        return y4m_asset


@pytest.fixture(scope='class', params=['jpeg_asset', 'png_asset', 'mp3_asset', 'wav_asset', 'mp4_asset', 'y4m_asset'])
def asset(request, jpeg_asset, png_asset, gif_asset, mp3_asset, wav_asset, mp4_asset, y4m_asset):
    if request.param == 'jpeg_asset':
        return jpeg_asset
    elif request.param == 'png_asset':
        return png_asset
    elif request.param == 'gif_asset':
        return gif_asset
    elif request.param == 'mp3_asset':
        return mp3_asset
    elif request.param == 'opus_asset':
        return opus_asset
    elif request.param == 'wav_asset':
        return wav_asset
    elif request.param == 'mp4_asset':
        return mp4_asset
    else:
        return y4m_asset


@pytest.fixture
def unknown_asset():
    random_data = b'\x07]>e\x10\n+Y\x07\xd8\xf4\x90%\r\xbbK\xb8+\xf3v%\x0f\x11'
    return madam.core.Asset(essence=io.BytesIO(random_data),
                            mime_type='application/octet-stream')
