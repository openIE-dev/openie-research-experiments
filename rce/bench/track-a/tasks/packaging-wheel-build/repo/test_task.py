from packaging.utils import parse_wheel_filename
n, v, b, t = parse_wheel_filename('foo-1.0-1-py3-none-any.whl')
assert b == (1, '')
