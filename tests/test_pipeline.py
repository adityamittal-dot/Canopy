from parsing.pipeline import analyze_repo


def test_analyze_repo_end_to_end():
    result = analyze_repo('https://github.com/pypa/sampleproject')

    assert len(result['commit_hash']) == 40
    assert result['parse_failures'] == []
    assert len(result['nodes']) > 0
    assert all(n['kind'] in ('module', 'class', 'function') for n in result['nodes'])
    assert all('resolved' in e for e in result['edges'])
    assert len(result['imports']) > 0
