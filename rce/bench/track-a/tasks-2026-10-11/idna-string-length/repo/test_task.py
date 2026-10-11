from idna.core import valid_string_length
assert valid_string_length('a' * 254, True)
assert not valid_string_length('a' * 254, False)
