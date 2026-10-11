from packaging.utils import parse_sdist_filename
from packaging.version import Version
assert parse_sdist_filename('foo-bar-1.0.tar.gz') == ('foo-bar', Version('1.0'))
