from parsing.clone import clone_repo
from parsing.walk import find_python_files


def test_clone_and_walk_finds_python_files():
    path, commit_hash = clone_repo('https://github.com/pypa/sampleproject')

    assert len(commit_hash) == 40

    py_files = find_python_files(path)

    assert len(py_files) > 0
    assert all(f.endswith('.py') for f in py_files)
    assert not any('__pycache__' in f for f in py_files)
