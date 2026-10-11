from idna.core import valid_string_length
assert valid_string_length('a' * 254, True)
assert not valid_string_length('a' * 254, False)
assert valid_string_length('a' * 253, False)
assert not valid_string_length('a' * 255, True)
assert valid_string_length('a', True) and valid_string_length('a', False)
