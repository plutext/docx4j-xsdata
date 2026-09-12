from collections.abc import Callable, Iterator

import pytest

from tests.fork.utils import Generated, generate


@pytest.fixture
def gen() -> Iterator[Callable[..., Generated]]:
    """Generate throwaway packages and clean them up after the test.

    The cleanup must happen after the test function's frame is gone:
    while a generated class is still reachable, ``XmlContext`` finds it
    through ``object.__subclasses__()`` and other tests blow up on a
    module that is no longer in ``sys.modules``.
    """
    created: list[Generated] = []

    def factory(*args, **kwargs) -> Generated:
        obj = generate(*args, **kwargs)
        created.append(obj)
        return obj

    yield factory

    for obj in created:
        obj.cleanup()
