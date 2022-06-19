#!/usr/bin/env python
"""Setup for cambridgeavr module."""
from setuptools import setup


def readme():
    """Return README file as a string."""
    with open("README.rst", "r") as f:
        return f.read()


setup(
    name="cambridgeavr",
    version="1.0.0",
    author="Dario Breitenstein",
    author_email="online@imakethings.ch",
    url="https://github.com/chdabre/python-cambridgeavr",
    license="LICENSE",
    packages=["cambridgeavr"],
    scripts=[],
    description="Python API for controlling Cambridge Audio Receivers",
    long_description=readme(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    include_package_data=True,
    zip_safe=True,
    entry_points={
    },
)
