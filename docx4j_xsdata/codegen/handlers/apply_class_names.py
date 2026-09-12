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
    resolved, so a name that the table still makes ambiguous is
    disambiguated by the same numeric suffixes as any other duplicate.

    Two rules keep a table written from a JAXB model from shredding the
    output, because JAXB has one class where the generator has several:

    * A class the generator invented for one element of one compound
      field (`DisambiguateChoices`, `Class.scope_name`) is renamed only
      by a scoped entry, `t@CT_R`. JAXB had no class for those either,
      it had a `JAXBElement` per element name over the shared type.
    * An element entry that wants a name another class already owns is
      dropped, not applied and suffixed. `elements` in a JAXB derived
      table names the *payload* class of a `JAXBElement`, which the
      `types` section already names; letting both through would push the
      real class to `Text1` and spread `Text2`..`Text7` over the
      elements that share it.

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

        candidates = []
        for obj in self.container:
            new_name, from_element = self.find(table, obj)

            if new_name is not None and new_name != obj.name:
                candidates.append((obj, new_name, from_element))

        for obj, new_qname in self.resolve(candidates):
            self.rename_class(obj, new_qname)

        if self.renames:
            for target in self.container:
                self.update_references(target)

    @classmethod
    def find(cls, table: ClassNames, obj: Class) -> tuple[str | None, bool]:
        """Return the class name the table has for a class, and its source.

        An element class is looked up in the elements table. So is an
        anonymous type that UnnestClasses promoted out of the element
        that declared it, `R.T` for `w:t`, by the element name; the
        promoted name, `CT_R_t`, in the types table wins over it, which
        is the way out when an element and an attribute of the same name
        both declare an anonymous type.

        A class with a `scope_name` is one `DisambiguateChoices` created
        for a single element of a single compound field. Only a scoped
        entry, `t@CT_R`, reaches it.

        Args:
            table: The class name table
            obj: The class to look up

        Returns:
            The class name to emit or None to keep the conventions, and
            whether it came from the elements rather than the types
            section.
        """
        namespace = obj.target_namespace

        if obj.scope_name:
            return table.find_scoped(namespace, obj.name, obj.scope_name), True

        if obj.is_element:
            return table.find(namespace, obj.name, True), True

        if obj.local_type and obj.source_name:
            by_type = table.find(namespace, obj.name, False)
            if by_type is not None:
                return by_type, False
            return table.find(namespace, obj.source_name, True), True

        return table.find(namespace, obj.name, False), False

    def resolve(
        self, candidates: list[tuple[Class, str, bool]]
    ) -> list[tuple[Class, str]]:
        """Drop the renames that would collide and report them.

        The types section is applied first, so that the class the schema
        declares as a type keeps the bare name and the elements that
        merely reference it do not take it away from it.

        Args:
            candidates: The classes to rename, their new names and
                whether the name came from the elements section

        Returns:
            The accepted renames and their new qualified names.
        """
        renamed = {obj.ref for obj, _, _ in candidates}
        owners: dict[str, list[str]] = defaultdict(list)

        for obj in self.container:
            if obj.ref not in renamed:
                owners[text.alnum(obj.qname)].append(obj.name)

        accepted = []
        for obj, new_name, from_element in sorted(candidates, key=lambda c: c[2]):
            new_qname = namespaces.build_qname(obj.target_namespace, new_name)
            key = text.alnum(new_qname)
            others = owners[key]

            if others and from_element:
                logger.warning(
                    "ClassNames: element %s is left alone, `%s` belongs to %s",
                    obj.source_name or obj.name,
                    new_name,
                    others[0],
                )
                continue

            if others:
                logger.warning(
                    "ClassNames: %s is mapped to `%s`, which %s already owns; "
                    "the generator will add a numeric suffix",
                    obj.source_name or obj.name,
                    new_name,
                    others[0],
                )

            owners[key].append(obj.name)
            accepted.append((obj, new_qname))

        return accepted

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
