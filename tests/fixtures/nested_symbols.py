class Outer:
    class Inner:
        def method(self):
            pass

    def outer_method(self):
        def inner_function():
            pass

        return inner_function


async def fetch():
    pass


def top_level():
    pass
