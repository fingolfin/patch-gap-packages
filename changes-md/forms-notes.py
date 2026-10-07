from pathlib import Path

# condensed from the release notes in doc/intro.xml
NOTES = {
    "## 1.2.5 (2018-09-27)": """- Make some small changes to the recognition part
- Add examples to the manual that explain the functionality better""",
    "## 1.2.4 (2017-08-26)": """- Use `GAPInfo.RootPaths` instead of the deprecated `GAP_ROOT_PATHS`
- Fix a bug in one of the methods for `EvaluateForm`
- Use `Test` instead of the deprecated `ReadTest`, and add more tests
- Fix LaTeX issues in the manual""",
    "## 1.2.3 (2015-10-26)": """- Add `TypeOfForm`, and revise the documentation of degenerate and singular
  forms
- Fix the methods for `^` for a pair of vectors or of matrices and a hermitian
  form
- Add test files in the `tst` directory
- Fix the Windows line breaks in `init.g` and `read.g`
- Build the manual with MathJax""",
}
OLDER = """## 1.2.2

- Fix a bug in `IsTotallyIsotropicSubspace`
- Rename some global functions to avoid name clashes with GAP 4.5; this
  version works with GAP 4.4 and 4.5

## 1.2.1

- Change and extend the functionality for trivial forms
"""

p = Path("forms/CHANGES.md")
t = p.read_text()
for header, notes in NOTES.items():
    assert t.count(header + "\n") == 1
    t = t.replace(header + "\n", header + "\n\n" + notes + "\n", 1)
assert t.endswith("## 1.2.3 (2015-10-26)\n\n" + NOTES["## 1.2.3 (2015-10-26)"] + "\n")
p.write_text(t + "\n" + OLDER)
