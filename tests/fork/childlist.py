"""A stand-in for docx4j-python's ChildList, for the ListFactory tests.

The real one lives in docx4j-python and is the analogue of docx4j's
`org.docx4j.list.ArrayListDocx4j`: a list subclass that sets the parent
pointer of everything put into it.
"""

from typing import Any


class ChildList(list):
    """A list that remembers it is the owner of what it holds."""

    def append(self, item: Any) -> None:
        """Append an item and claim it."""
        super().append(item)
        object.__setattr__(item, "parent", self)
