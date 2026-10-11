from packaging.utils import canonicalize_name
assert canonicalize_name('Foo_Bar.baz') == 'foo-bar-baz'
