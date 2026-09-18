from collections.abc import Iterable
from typing import Any

from lxml import etree

from docx4j_xsdata.exceptions import XmlHandlerError
from docx4j_xsdata.formats.dataclass.parsers.mixins import XmlHandler
from docx4j_xsdata.models.enums import EventType

EVENTS = (EventType.START, EventType.END, EventType.START_NS)


class LxmlEventHandler(XmlHandler):
    """An lxml event handler."""

    def parse(self, source: Any, ns_map: dict[str | None, str]) -> Any:
        """Parse the source XML document.

        Args:
            source: The xml source, can be a file resource or an input stream,
                or a lxml tree/element.
            ns_map: A namespace prefix-URI recorder map

        Returns:
            An instance of the class type representing the parsed content.
        """
        if isinstance(source, (etree._ElementTree, etree._Element)):
            ctx = etree.iterwalk(source, EVENTS)
        elif self.parser.config.process_xinclude:
            tree = etree.parse(source, base_url=self.parser.config.base_url)  # nosec
            tree.xinclude()
            ctx = etree.iterwalk(tree, EVENTS)
        else:
            ctx = etree.iterparse(
                source,
                EVENTS,
                recover=True,
                remove_comments=True,
                load_dtd=self.parser.config.load_dtd,
            )

        return self.process_context(ctx, ns_map)

    def process_context(
        self,
        context: Iterable[tuple[str, Any]],
        ns_map: dict[str | None, str],
    ) -> Any:
        """Iterate context and push events to main parser.

        Args:
            context: The iterable lxml context
            ns_map: A namespace prefix-URI recorder map

        Returns:
            An instance of the class type representing the parsed content.
        """
        # docx4j fork: the loop runs once per element of every document, so the
        # things that do not change over it --- the parser's three bound
        # methods, the node queue, the object list and the event names --- are
        # looked up once rather than on every event.
        parser = self.parser
        start = parser.start
        end = parser.end
        register_namespace = parser.register_namespace
        clazz = self.clazz
        queue = self.queue
        objects = self.objects
        start_event = EventType.START
        end_event = EventType.END
        start_ns_event = EventType.START_NS

        for event, element in context:
            if event == start_event:
                start(
                    clazz,
                    queue,
                    objects,
                    element.tag,
                    element.attrib,
                    element.nsmap,
                )
            elif event == end_event:
                end(
                    queue,
                    objects,
                    element.tag,
                    element.text,
                    element.tail,
                )
                element.clear()
            elif event == start_ns_event:
                prefix, uri = element
                register_namespace(ns_map, prefix or None, uri)
            else:
                raise XmlHandlerError(f"Unhandled event: `{event}`.")

        return self.objects[-1][1] if self.objects else None
