from collections import defaultdict

from docx4j_xsdata.codegen.class_names import ClassNames
from docx4j_xsdata.codegen.mixins import ContainerHandlerInterface, ContainerInterface
from docx4j_xsdata.codegen.models import Attr, Class
from docx4j_xsdata.logger import logger
from docx4j_xsdata.utils import namespaces, text


class ApplyClassNames(ContainerHandlerInterface):
    """docx4j fork: rename classes from the explicit name table.

    The table is `<Output><ClassNames>`, a directory of json files, one
    per namespace, mapping schema type and element names to the class
    names to emit. It runs before the duplicate class names are
    resolved, so a name that the table makes ambiguous is disambiguated
    by the same numeric suffixes as any other duplicate.

    Args:
        container: The class container instance

    Attributes:
        renames: The renamed class references and their new qualified names
    """

    __slots__ = "renames"

    def __init__(self, container: ContainerInterface):
        """Initialize the apply class names handler."""
        super().__init__(container)
        self.renames: dict[int, str] = {}

    def run(self) -> None:
        """Rename every class the name table knows."""
        table = self.container.config.output.class_name_table
        if table is None:
            return

        targets = []
        for obj in self.container:
            new_name = self.find(table, obj)

            if new_name is not None and new_name != obj.name:
                new_qname = namespaces.build_qname(obj.target_namespace, new_name)
                targets.append((obj, new_qname))

        self.warn_collisions(targets)

        for obj, new_qname in targets:
            self.rename_class(obj, new_qname)

        if self.renames:
            for target in self.container:
                self.update_references(target)

    @classmethod
    def find(cls, table: ClassNames, obj: Class) -> str | None:
        """Return the class name the table has for a class, or None.

        An element class is looked up in the elements table. So is an
        anonymous type that UnnestClasses promoted out of the element
        that declared it, `R.T` for `w:t`, by the element name; the
        promoted name, `CT_R_t`, in the types table wins over it, which
        is the way out when an element and an attribute of the same name
        both declare an anonymous type.

        Args:
            table: The class name table
            obj: The class to look up

        Returns:
            The class name to emit, or None to keep the conventions.
        """
        namespace = obj.target_namespace

        if obj.is_element:
            return table.find(namespace, obj.name, True)

        if obj.local_type and obj.source_name:
            return table.find(namespace, obj.name, False) or table.find(
                namespace, obj.source_name, True
            )

        return table.find(namespace, obj.name, False)

    def warn_collisions(self, targets: list[tuple[Class, str]]) -> None:
        """Report the mapped names that another class already owns.

        The classes are not merged or overwritten, the duplicate class
        names handler adds a numeric suffix to them, as it does for any
        other clash.

        Args:
            targets: The classes to rename and their new qualified names
        """
        renamed = {obj.ref for obj, _ in targets}
        owners: dict[str, list[str]] = defaultdict(list)

        for obj in self.container:
            if obj.ref not in renamed:
                owners[text.alnum(obj.qname)].append(obj.name)

        for obj, new_qname in targets:
            key = text.alnum(new_qname)
            others = owners[key]
            if others:
                logger.warning(
                    "ClassNames: %s is mapped to `%s`, which %s already owns; "
                    "the generator will add a numeric suffix",
                    obj.source_name or obj.name,
                    namespaces.local_name(new_qname),
                    others[0],
                )
            owners[key].append(obj.name)

    def rename_class(self, target: Class, new_qname: str) -> None:
        """Update the class qualified name and schedule updates.

        Args:
            target: The target class to update
            new_qname: The new qualified name of the class
        """
        qname = target.qname
        target.meta_name = (
            target.meta_name or target.source_name or namespaces.local_name(qname)
        )
        target.qname = new_qname

        self.container.reset(target, qname)
        self.renames[target.ref] = new_qname

    def update_references(self, target: Class) -> None:
        """Search and update the target class for renamed references.

        Args:
            target: The target class instance to inspect and update
        """
        for parent, tp in target.types_with_parents():
            if tp.reference in self.renames:
                tp.qname = self.renames[tp.reference]

                if (
                    isinstance(parent, Attr)
                    and isinstance(parent.default, str)
                    and parent.default.startswith("@enum@")
                ):
                    members = text.suffix(parent.default, "::")
                    parent.default = f"@enum@{tp.qname}::{members}"
