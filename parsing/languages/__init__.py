from parsing.languages.base import LANGUAGE_REGISTRY, analyzer_for
from parsing.languages import specs  # noqa: F401 - populates LANGUAGE_REGISTRY on import

__all__ = ['LANGUAGE_REGISTRY', 'analyzer_for']
