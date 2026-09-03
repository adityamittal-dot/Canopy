from parsing.extract import Symbol


def compute_loc(symbol: Symbol) -> int:
    """Lines of code spanned by `symbol`, from its recorded line range."""
    if symbol.end_lineno is None:
        return 0
    return symbol.end_lineno - symbol.lineno + 1
