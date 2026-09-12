import logging
import re

from toposort import toposort_flatten

from docx4j_xsdata.codegen.exceptions import CodegenError
from docx4j_xsdata.codegen.models import Class, Import, get_slug
from docx4j_xsdata.utils import collections

logger = logging.getLogger(__name__)


class DependenciesResolver:
    """The dependencies resolver class.

    Calculate what classes need to be imported
    per package, with aliases support.

    Args:
        registry: The full class qname-module map.
        defer_imports: docx4j fork: split the imports into the ones the
            module needs while its classes are being created and the ones
            it only needs afterwards.

    Attributes:
        aliases: The generated aliases dictionary
        imports: The list of generated imports
        class_list: The topo-sorted list of class qnames
        class_map: A qname-class map
        deferred: The qnames of the imports that can wait

    """

    __slots__ = (
        "aliases",
        "class_list",
        "class_map",
        "defer_imports",
        "deferred",
        "imports",
        "registry",
    )

    def __init__(self, registry: dict[str, str], defer_imports: bool = False):
        """Initialize the resolver."""
        self.registry = registry
        self.defer_imports = defer_imports
        self.aliases: dict[str, str] = {}
        self.imports: list[Import] = []
        self.deferred: set[str] = set()
        self.class_list: list[str] = []
        self.class_map: dict[str, Class] = {}

    def process(self, classes: list[Class]) -> None:
        """Resolve the dependencies for the given class list.

        Reset previously resolved imports and aliases.

        Args:
            classes: A list of classes that belong to the same target module
        """
        self.imports.clear()
        self.aliases.clear()
        self.deferred.clear()
        self.class_map = self.create_class_map(classes)
        self.class_list = self.create_class_list(classes)
        self.resolve_imports()

    def sorted_imports(self) -> list[Import]:
        """Return a new sorted by name list of import instances.

        With deferred imports enabled, only the ones the module needs
        while its own classes are being created.
        """
        return sorted(
            (imp for imp in self.imports if imp.qname not in self.deferred),
            key=lambda x: x.name,
        )

    def eager_modules(self) -> set[str]:
        """Return the modules this module must be imported after."""
        return {imp.source for imp in self.imports if imp.qname not in self.deferred}

    def deferred_modules(self) -> set[str]:
        """Return the modules this module imports below its classes."""
        return {imp.source for imp in self.imports if imp.qname in self.deferred}

    def sorted_deferred_imports(self) -> list[Import]:
        """Return the imports that belong at the bottom of the module.

        docx4j fork, CR-001 section 6.1: one package per namespace means
        modules that import each other, because WML embeds DML and DML
        embeds WML through `a:graphicData`. Postponed annotations make the
        type hints strings already, so the only names a module really needs
        while its classes are being created are its base classes and the
        values it puts in `default=`; everything else can be imported after
        the classes exist, which breaks the cycle.
        """
        return sorted(
            (imp for imp in self.imports if imp.qname in self.deferred),
            key=lambda x: x.name,
        )

    def sorted_classes(self) -> list[Class]:
        """Apply aliases and return the sorted the generated class list."""
        result = []
        for name in self.class_list:
            obj = self.class_map.get(name)
            if obj is not None:
                self.apply_aliases(obj)
                result.append(obj)
        return result

    def apply_aliases(self, target: Class) -> None:
        """Apply import aliases to the target class.

        Update attr and extension types to point to the
        new class aliases. Process inner classes too!

        Args:
            target: The target class instance to process
        """
        for attr in target.attrs:
            for attr_type in attr.types:
                attr_type.alias = self.aliases.get(attr_type.qname)

            for choice in attr.choices:
                for choice_type in choice.types:
                    choice_type.alias = self.aliases.get(choice_type.qname)

        for ext in target.extensions:
            ext.type.alias = self.aliases.get(ext.type.qname)

        collections.apply(target.inner, self.apply_aliases)

    def resolve_imports(self) -> None:
        """Build the list of class imports and set aliases if necessary."""
        imported = self.import_classes()
        if self.defer_imports:
            eager: set[str] = set()
            for obj in self.class_map.values():
                self.collect_eager_dependencies(obj, eager)
            self.deferred = {qname for qname in imported if qname not in eager}

        self.imports = [
            Import(qname=qname, source=self.get_class_module(qname))
            for qname in imported
        ]
        protected = {obj.slug for obj in self.class_map.values()}
        self.resolve_conflicts(self.imports, protected)
        self.set_aliases()

    def set_aliases(self) -> None:
        """Store generated aliases."""
        self.aliases = {imp.qname: imp.alias for imp in self.imports if imp.alias}

    @classmethod
    def resolve_conflicts(cls, imports: list[Import], protected: set):
        """Find naming conflicts between imports and generate aliases.

        Example:
            from foo.bar import MyType as BarMyType
            from bar.foo import MyType as FooMyType

        Args:
            imports: The list of class import instances
            protected: The set of protected class names from the module
        """
        for slug, group in collections.group_by(imports, key=get_slug).items():
            if len(group) == 1:
                if slug in protected:
                    imp = group[0]
                    module = imp.source.split(".")[-1]
                    imp.alias = f"{module}:{imp.name}"
                continue

            for index, cur in enumerate(group):
                cmp = group[index + 1] if index == 0 else group[index - 1]
                parts = re.split("[_.]", cur.source)
                diff = set(parts) - set(re.split("[_.]", cmp.source))

                add = "_".join(part for part in parts if part in diff)
                cur.alias = f"{add}:{cur.name}"

    @classmethod
    def collect_eager_dependencies(cls, target: Class, result: set[str]) -> None:
        """Collect the qnames the target class needs at class creation time.

        Which are:
            - its base classes, and the base classes of its inner classes
            - anything a field default value refers to, e.g. an enum member
            - every type of an enumeration or a service class, their
              members are rendered as class references

        Args:
            target: The class instance to inspect
            result: The set of qnames to update
        """
        for ext in target.extensions:
            result.add(ext.type.qname)

        constants = target.is_enumeration or target.is_service
        for attr in target.attrs:
            if constants or attr.default is not None:
                result.update(tp.qname for tp in attr.user_types)

            for choice in attr.choices:
                if choice.default is not None:
                    result.update(tp.qname for tp in choice.user_types)

        for inner in target.inner:
            cls.collect_eager_dependencies(inner, result)

    def get_class_module(self, qname: str) -> str:
        """Return the module for the given qualified class name.

        Args:
            qname: The namespace qualified name of the class

        Raises:
            CodeGenerationError: if name doesn't exist.
        """
        if qname not in self.registry:
            raise CodegenError("Failed to resolve dependency", qname=qname)
        return self.registry[qname]

    def import_classes(self) -> list[str]:
        """Return a list of class qnames that need to be imported."""
        result = [qname for qname in self.class_list if qname not in self.class_map]
        if self.defer_imports:
            result.extend(self.circular_imports(result))
        return result

    def circular_imports(self, imported: list[str]) -> list[str]:
        """Return the circular references that live in another module.

        docx4j fork. A circular reference is generated as a quoted forward
        reference and is deliberately left out of the topological sort, which
        is right while the two classes share a module. Under a per namespace
        layout they often do not, and then the name still has to come from
        somewhere.
        """
        if not self.class_map:
            return []

        module = next(iter(self.class_map.values())).target_module
        seen = set(imported) | set(self.class_map)
        result = []
        for obj in self.class_map.values():
            for qname in obj.dependencies(allow_circular=True):
                if qname in seen or self.registry.get(qname) in (None, module):
                    continue
                seen.add(qname)
                result.append(qname)

        return result

    @staticmethod
    def create_class_list(classes: list[Class]) -> list[str]:
        """Use topology sort to return a flat list for all the dependencies."""
        return toposort_flatten({obj.qname: set(obj.dependencies()) for obj in classes})

    @staticmethod
    def create_class_map(classes: list[Class]) -> dict[str, Class]:
        """Index the list of classes by their qualified names.

        Raises:
            CodeGenerationError: If two classes have the same qname.

        Returns:
            A qname-class map.
        """
        result: dict[str, Class] = {}
        for obj in classes:
            if obj.qname in result:
                raise CodegenError("Duplicate class during resolve", qname=obj.qname)
            result[obj.qname] = obj

        return result
