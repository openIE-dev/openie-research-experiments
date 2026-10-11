from packaging.version import Version
assert Version('1.2').micro == 0
assert Version('1.2.3').micro == 3
