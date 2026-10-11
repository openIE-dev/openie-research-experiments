from packaging.version import Version
assert Version('1.0.post1.dev0') > Version('1.0')
assert Version('1.0.dev0') < Version('1.0a0')
