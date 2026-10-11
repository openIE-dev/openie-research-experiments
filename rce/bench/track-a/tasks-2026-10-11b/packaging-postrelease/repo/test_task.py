from packaging.version import Version
assert Version('1.0.post1').is_postrelease
assert not Version('1.0').is_postrelease
