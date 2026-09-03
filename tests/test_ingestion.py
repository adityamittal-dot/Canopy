from parsing.clone import CloneError, clone_repo, get_remote_head_commit
from parsing.walk import find_python_files


def test_clone_and_walk_finds_python_files():
    path, commit_hash = clone_repo('https://github.com/pypa/sampleproject')

    assert len(commit_hash) == 40

    py_files = find_python_files(path)

    assert len(py_files) > 0
    assert all(f.endswith('.py') for f in py_files)
    assert not any('__pycache__' in f for f in py_files)


def test_get_remote_head_commit_matches_clone_without_cloning():
    _, cloned_commit_hash = clone_repo('https://github.com/pypa/sampleproject')

    remote_commit_hash = get_remote_head_commit('https://github.com/pypa/sampleproject')

    assert remote_commit_hash == cloned_commit_hash


def test_get_remote_head_commit_raises_on_bad_url():
    try:
        get_remote_head_commit('https://github.com/this-user-does-not-exist-abcxyz/nope')
        assert False, 'expected CloneError'
    except CloneError:
        pass
