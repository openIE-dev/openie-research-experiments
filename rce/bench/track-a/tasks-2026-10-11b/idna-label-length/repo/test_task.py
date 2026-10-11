from idna.core import valid_label_length
assert not valid_label_length('a' * 64)
assert valid_label_length('a' * 63)
