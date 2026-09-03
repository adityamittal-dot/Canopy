from parsing.extract import Symbol


def build_symbol_table(symbols: list[Symbol]) -> dict[str, Symbol]:
    """Map fully-qualified name -> Symbol, across every file's extracted symbols."""
    return {symbol.name: symbol for symbol in symbols}
