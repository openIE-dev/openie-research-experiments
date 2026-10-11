from packaging.utils import parse_wheel_filename
n, v, b, t = parse_wheel_filename('foo-1.0-1-py3-none-any.whl')
assert b == (1, '')
n, v, b, t = parse_wheel_filename('foo-1.0-py3-none-any.whl')
assert (n, str(v), b) == ('foo', '1.0', ())
try:
    parse_wheel_filename('foo-1.0-any.whl')
    raise SystemExit('accepted a wheel with too few parts')
except ValueError:
    pass
