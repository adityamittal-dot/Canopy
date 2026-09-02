name = "world"
greeting = f"hello, {name}!"


def read_lines(path):
    lines = []
    with open(path) as f:
        while (line := f.readline()):
            lines.append(line)
    return lines


def describe(value):
    match value:
        case int():
            return "an int"
        case str():
            return "a string"
        case _:
            return "something else"
