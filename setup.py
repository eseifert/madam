#!/usr/bin/env python

from setuptools import setup

setup(
    name='MADAM',
    version='0.1',
    author='Michael Seifert',
    author_email='mseifert@error-reports.org',
    install_requires=['piexif', 'pillow'],
    setup_requires=['pytest-runner'],
    tests_require=['piexif', 'pillow', 'pytest'],
)
