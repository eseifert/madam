import madam.video


def test_supports_y4m_file():
    ffmpeg_processor = madam.video.FFmpegProcessor()
    video_path = 'tests/bus_qcif_15fps.y4m'

    with open(video_path, 'rb') as video_file:
        supported = ffmpeg_processor.can_read(video_file)

    assert supported
