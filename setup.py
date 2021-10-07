from setuptools import setup
import pathlib
from docs import __version__

ROOT = pathlib.Path(__file__).parent

with open(f'{ROOT}/README.md', 'r', encoding='utf-8') as f:
    README = f.read()

with open(f'{ROOT}/requirements.txt', 'r', encoding='utf-8') as f:
    REQUIREMENTS = f.read().splitlines()

setup(
    name='disnake-docs',
    author='Kraots',
    url='https://github.com/Kraots/disnake_docs',

    description='A disnake extension that adds a docs command.',
    long_description=README,
    long_description_content_type='text/markdown',
    project_urls={
        'Code': 'https://github.com/Kraots/disnake_docs'
    },

    version=__version__,
    packages=['docs'],
    include_package_data=True,
    install_requires=REQUIREMENTS,
    python_requires='>=3.8.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Framework :: AsyncIO',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: Communications :: Chat',
        'Topic :: Internet',
        'Topic :: Software Development :: Debuggers',
        'Topic :: Software Development :: Testing',
        'Topic :: Utilities'
    ]
)
