from packaging.version import Version
assert Version('1.0.post1.dev0') > Version('1.0')
assert Version('1.0.dev0') < Version('1.0a0')
vs = ['1.0.dev0', '1.0a1', '1.0', '1.0.post1.dev0', '1.0.post1', '1.1']
assert sorted(vs, key=Version) == vs
assert sorted(reversed(vs), key=Version) == vs
assert not Version('1.0.post1') < Version('1.0')
