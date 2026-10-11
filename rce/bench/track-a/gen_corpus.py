#!/usr/bin/env python3
"""Builds the Track A corpus from real crate and package sources on this box.

Each task is a real source tree at a base state that carries one regression,
a failing test, and a gold patch that restores the released code.
Rust sources come from the vendored cargo registry. Python sources come
from the system dist-packages. Run: python3 gen_corpus.py (idempotent).
"""
import difflib, glob, json, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REG = glob.glob(os.path.expanduser("~/.cargo/registry/src/index.crates.io-*"))[0]
PY = "/usr/lib/python3/dist-packages"
SANDBOX = "unshare -rn sh -c "  # no network, unprivileged user namespace
RUST_TEST = SANDBOX + "'CARGO_TARGET_DIR=$PWD/target cargo test --offline -q --lib > .test.out 2>&1; e=$?; tail -40 .test.out; exit $e'"

# Rust tasks whose crate tests miss the regression carry the regression test.
EXTRA = {
 "shlex-lineno": "\n#[cfg(test)]\nmod task_regression {\n    #[test]\n    fn line_no_counts_each_newline_once() {\n        let mut sh = crate::Shlex::new(\"a\\nb\\n\\nc d\");\n        let words: Vec<String> = sh.by_ref().collect();\n        assert_eq!(words, vec![\"a\", \"b\", \"c\", \"d\"]);\n        assert_eq!(sh.line_no, 4);\n        let mut one = crate::Shlex::new(\"x\\n\");\n        assert_eq!(one.next(), Some(\"x\".to_string()));\n        assert_eq!(one.next(), None);\n        assert_eq!(one.line_no, 2);\n    }\n}\n",
 "strsim-damerau-match": "\n#[cfg(test)]\nmod task_regression {\n    #[test]\n    fn damerau_equal_is_zero() {\n        assert_eq!(crate::generic_damerau_levenshtein(&[1, 2, 3], &[1, 2, 3]), 0);\n        assert_eq!(crate::generic_damerau_levenshtein(&[1, 2], &[2, 1]), 1);\n    }\n}\n",
 "shlex-newline-split": "\n#[cfg(test)]\nmod task_regression {\n    #[test]\n    fn split_ends_word_at_newline() {\n        assert_eq!(crate::split(\"a\\nb\"), Some(vec![\"a\".to_string(), \"b\".to_string()]));\n    }\n}\n",
}

# (id, kind, source, file, released text, regressed text, problem, python test or None)
T = [
 ("strsim-levenshtein-row", "rust", "strsim-0.11.1", "src/lib.rs", "result = i + 1;", "result = i;",
  "levenshtein undercounts: levenshtein(\"kitten\", \"sitting\") is wrong.", None),
 ("strsim-osa-cost", "rust", "strsim-0.11.1", "src/lib.rs", "min(prev_distances[j + 1] + 1, prev_distances[j] + cost),", "min(prev_distances[j + 1] + 1, prev_distances[j] + 1),",
  "osa_distance counts equal characters as substitutions.", None),
 ("strsim-jaro-lower-bound", "rust", "strsim-0.11.1", "src/lib.rs", "if min_bound <= j && a_elem == b_elem", "if min_bound < j && a_elem == b_elem",
  "jaro misses matches at the lower edge of the search window.", None),
 ("strsim-jaro-upper-bound", "rust", "strsim-0.11.1", "src/lib.rs", "let max_bound = min(b_len, i + search_range + 1);", "let max_bound = min(b_len, i + search_range);",
  "jaro misses matches at the upper edge of the search window.", None),
 ("strsim-damerau-match", "rust", "strsim-0.11.1", "src/lib.rs", "if a_elems[i - 1] == b_elems[j - 1] {", "if a_elems[i - 1] != b_elems[j - 1] {",
  "damerau_levenshtein charges a substitution for equal characters.", None),
 ("heck-final-sigma", "rust", "heck-0.5.0", "src/lib.rs", "if c == 'Σ' && chars.peek().is_none() {", "if c == 'Σ' && chars.peek().is_some() {",
  "Final sigma is lowercased to the medial form in snake case.", None),
 ("heck-capitalize-rest", "rust", "heck-0.5.0", "src/lib.rs", "            lowercase(&s[i..], f)?;", "            uppercase(&s[i..], f)?;",
  "UpperCamelCase leaves the rest of each word in upper case.", None),
 ("shlex-backslash-newline", "rust", "shlex-2.0.1", "src/bytes.rs", "if ch2 != b'\\n' { result.push(ch2); }", "result.push(ch2);",
  "A backslash before a newline outside quotes keeps the newline.", None),
 ("shlex-newline-split", "rust", "shlex-2.0.1", "src/bytes.rs", "' ' | '\\t' | '\\n' => { break; },", "' ' | '\\t' => { break; },",
  "split does not end a word at a newline.", None),
 ("shlex-error-none", "rust", "shlex-2.0.1", "src/bytes.rs", "if shl.had_error { None } else { Some(res) }", "Some(res)",
  "split returns Some for an unterminated quote.", None),
 ("shlex-lineno", "rust", "shlex-2.0.1", "src/bytes.rs", "if res == Some(b'\\n') { self.line_no += 1; }", "if res == Some(b'\\n') { self.line_no += 2; }",
  "Shlex::line_no advances two lines per newline.", None),
 ("packaging-minor", "py", "packaging", "packaging/version.py", "return self.release[1] if len(self.release) >= 2 else 0", "return self.release[1] if len(self.release) > 2 else 0",
  "Version('1.2').minor is 0.", "from packaging.version import Version\nassert Version('1.2').minor == 2\nassert Version('1').minor == 0\n"),
 ("packaging-micro", "py", "packaging", "packaging/version.py", "return self.release[2] if len(self.release) >= 3 else 0", "return self.release[2] if len(self.release) >= 3 else 1",
  "Version('1.2').micro is 1.", "from packaging.version import Version\nassert Version('1.2').micro == 0\nassert Version('1.2.3').micro == 3\n"),
 ("packaging-postrelease", "py", "packaging", "packaging/version.py", "return self.post is not None", "return self.post is None",
  "is_postrelease is inverted.", "from packaging.version import Version\nassert Version('1.0.post1').is_postrelease\nassert not Version('1.0').is_postrelease\n"),
 ("packaging-dev-of-post", "py", "packaging", "packaging/version.py", "if pre is None and post is None and dev is not None:", "if pre is None and dev is not None:",
  "1.0.post1.dev0 sorts before 1.0.", "from packaging.version import Version\nassert Version('1.0.post1.dev0') > Version('1.0')\nassert Version('1.0.dev0') < Version('1.0a0')\nvs = ['1.0.dev0', '1.0a1', '1.0', '1.0.post1.dev0', '1.0.post1', '1.1']\nassert sorted(vs, key=Version) == vs\nassert sorted(reversed(vs), key=Version) == vs\nassert not Version('1.0.post1') < Version('1.0')\n"),
 ("packaging-sdist-dash", "py", "packaging", "packaging/utils.py", "file_stem.rpartition(\"-\")", "file_stem.partition(\"-\")",
  "parse_sdist_filename fails on names that contain a dash.", "from packaging.utils import parse_sdist_filename\nfrom packaging.version import Version\nassert parse_sdist_filename('foo-bar-1.0.tar.gz') == ('foo-bar', Version('1.0'))\n"),
 ("packaging-wheel-build", "py", "packaging", "packaging/utils.py", "if dashes not in (4, 5):", "if dashes != 4:",
  "parse_wheel_filename rejects wheels with a build tag.", "from packaging.utils import parse_wheel_filename\nn, v, b, t = parse_wheel_filename('foo-1.0-1-py3-none-any.whl')\nassert b == (1, '')\nn, v, b, t = parse_wheel_filename('foo-1.0-py3-none-any.whl')\nassert (n, str(v), b) == ('foo', '1.0', ())\ntry:\n    parse_wheel_filename('foo-1.0-any.whl')\n    raise SystemExit('accepted a wheel with too few parts')\nexcept ValueError:\n    pass\ntry:\n    parse_wheel_filename('foo-1.0-1-py3-none-any-x.whl')\n    raise SystemExit('accepted a wheel with too many parts')\nexcept ValueError:\n    pass\n"),
 ("packaging-canonical-lower", "py", "packaging", "packaging/utils.py", "value = _canonicalize_regex.sub(\"-\", name).lower()", "value = _canonicalize_regex.sub(\"-\", name)",
  "canonicalize_name keeps upper case.", "from packaging.utils import canonicalize_name\nassert canonicalize_name('Foo_Bar.baz') == 'foo-bar-baz'\n"),
 ("idna-label-length", "py", "idna", "idna/core.py", "if len(label) > 63:", "if len(label) > 64:",
  "A 64-octet label is accepted.", "from idna.core import valid_label_length\nassert not valid_label_length('a' * 64)\nassert valid_label_length('a' * 63)\n"),
 ("idna-string-length", "py", "idna", "idna/core.py", "if len(label) > (254 if trailing_dot else 253):", "if len(label) > (253 if trailing_dot else 254):",
  "The 253/254 octet limit is swapped for the trailing dot.", "from idna.core import valid_string_length\nassert valid_string_length('a' * 254, True)\nassert not valid_string_length('a' * 254, False)\nassert valid_string_length('a' * 253, False)\nassert not valid_string_length('a' * 255, True)\nassert valid_string_length('a', True) and valid_string_length('a', False)\n"),
]

def udiff(path, a, b):
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), "a/" + path, "b/" + path))

def build(sub="tasks"):
    out = os.path.join(HERE, sub)
    names = []
    for (tid, kind, src, f, good, bad, problem, test) in T:
        d = os.path.join(out, tid)
        shutil.rmtree(d, ignore_errors=True)
        repo = os.path.join(d, "repo")
        if kind == "rust":
            shutil.copytree(os.path.join(REG, src), repo, ignore=shutil.ignore_patterns("benches", "tests", "target", ".cargo-ok", ".cargo_vcs_info.json"))
            ct = open(os.path.join(repo, "Cargo.toml")).read().split("\n[")
            keep = [s for s in ct if not (s.startswith("dev-dependencies") or s.startswith("[bench") or s.startswith("[test") or s.startswith("[example"))]
            open(os.path.join(repo, "Cargo.toml"), "w").write("\n[".join(keep))
            for l in ("Cargo.lock",):
                p = os.path.join(repo, l)
                if os.path.exists(p): os.remove(p)
            test_cmd = RUST_TEST
        else:
            os.makedirs(repo)
            shutil.copytree(os.path.join(PY, src), os.path.join(repo, src), ignore=shutil.ignore_patterns("__pycache__"))
            open(os.path.join(repo, "test_task.py"), "w").write(test)
            test_cmd = SANDBOX + "'python3 -B test_task.py'"
        p = os.path.join(repo, f)
        text = open(p, encoding="utf-8").read()
        assert text.count(good) == 1, (tid, text.count(good))
        broken = text.replace(good, bad)
        if tid in EXTRA:
            broken += EXTRA[tid]; text += EXTRA[tid]
        open(p, "w", encoding="utf-8").write(broken)
        open(os.path.join(d, "gold.patch"), "w").write(udiff(f, broken, text))
        json.dump({"id": tid, "problem": problem, "repo": "repo", "test_cmd": test_cmd, "gold_patch": "gold.patch",
                   "timeout_s": 600, "source": f"{src} ({'crates.io registry' if kind == 'rust' else 'dist-packages'})", "file": f},
                  open(os.path.join(d, "task.json"), "w"), indent=1)
        names.append(sub + "/" + tid)
    return names

if __name__ == "__main__":
    print("\n".join(build(sys.argv[1] if len(sys.argv) > 1 else "tasks")))
