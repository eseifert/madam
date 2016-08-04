#!/usr/bin/env python

from setuptools import setup

import versioneer

setup(
    name='MADAM',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author='Michael Seifert, Erich Seifert',
    author_email='mseifert@error-reports.org, dev@erichseifert.de',
    install_requires=['bidict', 'mutagen', 'piexif', 'pillow'],
    setup_requires=['pytest-runner', 'versioneer'],
    tests_require=['piexif', 'pillow', 'pytest'],
    packages=['madam'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Multimedia :: Graphics :: Graphics Conversion'
    ]
)
