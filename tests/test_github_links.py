from explorer.github_links import github_blob_url, parse_github_owner_repo


def test_parse_github_owner_repo_from_a_normal_url():
    assert parse_github_owner_repo('https://github.com/pallets/flask') == ('pallets', 'flask')


def test_parse_github_owner_repo_strips_git_suffix():
    assert parse_github_owner_repo('https://github.com/pallets/flask.git') == ('pallets', 'flask')


def test_parse_github_owner_repo_returns_none_for_non_github_host():
    assert parse_github_owner_repo('https://gitlab.com/pallets/flask') is None


def test_parse_github_owner_repo_returns_none_for_a_bare_host():
    assert parse_github_owner_repo('https://github.com/') is None


def test_github_blob_url_without_line_range():
    url = github_blob_url('https://github.com/pallets/flask', 'abc123', 'src/flask/app.py')
    assert url == 'https://github.com/pallets/flask/blob/abc123/src/flask/app.py'


def test_github_blob_url_with_single_line():
    url = github_blob_url('https://github.com/pallets/flask', 'abc123', 'src/flask/app.py', lineno=10)
    assert url == 'https://github.com/pallets/flask/blob/abc123/src/flask/app.py#L10'


def test_github_blob_url_with_line_range():
    url = github_blob_url('https://github.com/pallets/flask', 'abc123', 'src/flask/app.py', lineno=10, end_lineno=20)
    assert url == 'https://github.com/pallets/flask/blob/abc123/src/flask/app.py#L10-L20'


def test_github_blob_url_returns_none_for_non_github_host():
    assert github_blob_url('https://gitlab.com/pallets/flask', 'abc123', 'app.py') is None
