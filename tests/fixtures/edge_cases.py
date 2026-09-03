from functools import wraps


def decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


class Widget:
    @decorator
    def __init__(self):
        self.squares = [x * x for x in range(10)]
        self.adder = lambda a, b: a + b

    def __str__(self):
        return "Widget"

    async def refresh(self):
        pass
