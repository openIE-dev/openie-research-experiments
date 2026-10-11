from packaging.version import Version
assert Version('1.2').minor == 2
assert Version('1').minor == 0
