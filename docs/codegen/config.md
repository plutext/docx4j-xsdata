# Configuration

The command line tool includes most but not all available options. The most advanced
settings can be enabled through a project configuration file.

## Create or Update

You can create a default one with the command:

```console exec="1" source="console"
$ docx4j-xsdata init-config --help
```

**Output:** `.xsdata.xml `

```python exec="true" result="xml"
from io import StringIO
from docx4j_xsdata.models.config import GeneratorConfig

config = GeneratorConfig.create()
output = StringIO()
config.write(output, config)
print(output.getvalue())
```

**Usage**

```console
$ docx4j-xsdata generate --config project/.xsdata.xml
```

!!! Info "CLI options override the project configuration settings."

## Output Settings

Configuration settings related to output generation.

### `maxLineLength`

The maximum line length of the generated code.

**Default Value:** `79`

**CLI Option:** `-mll, --max-line-length INTEGER`

### `genericCollections`

Use `collections.abc.Iterable` and `collections.abc.Mapping` instead of `List|Tuple` and
`Dict`

**Default Value:** `False`

**CLI Option:** `--generic-collections / --no-generic-collections`

### Package

The output package for the generated code, e.g. `code.models`

**Default Value:** `generated`

**CLI Option:** `-p, --package TEXT`

!!! Warning

    Formatting and linting is executed on any directory that contains a Python file
    created during generation, including other Python files in the same directory prior
    to generation. As such it is recommended that the directories represented by this
    option do not include any previously created files.

### Format

The output format for the generated code, e.g. `code.models`

**Default Value:** `dataclasses`

**CLI Option:** `-o, --output TEXT`

**Attributes**

The [dataclass][dataclasses.dataclass] parameters.

- `repr`: Generate the [**repr**][object.__repr__] method.
- `eq`: Generate the [**eq**][object.__eq__] method.
- `order`: Generates the [**lt**][object.__lt__], [**le**][object.__le__],
  [**gt**][object.__gt__], [**ge**][object.__ge__] methods.
- `frozen`: This emulates read-only frozen instances.
- `unsafeHash`: Generates a [**hash**][object.__hash__] method according to how `eq` and
  `frozen` are set.
- `slots`: Generates the class [**slots**][object.__slots__] attribute. `python >= 3.10`

!!! Warning

    A TypeError is raised if a field without a default value follows a field with a default value.
    This is true whether this occurs in a single class, or as a result of class inheritance. If
    this option is not enabled, the generator will mark all required fields without default values
    as optional with default value `None`.

### Structure

The file structure style to create.

| Style                | Description                                                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `filenames`          | Group classes by the resource file location.                                                                              |
| `namespaces`         | Group classes by the target namespace.                                                                                    |
| `clusters`           | Group classes by strongly connected dependencies. The closest thing to one-class-per-package, safe from circular imports. |
| `single-package`     | Group classes in a single package. Safe from circular imports, but can create some huge files.                            |
| `namespace-clusters` | Group classes by strongly connected dependencies and target namespaces.                                                   |

**Default Value:** `filenames`

**CLI Option:**
`-ss, --structure-style [filenames|namespaces|clusters|single-package|namespace-clusters]`

### DocstringStyle

The style of docstrings to create.

**Default Value:** `reStructuredText`

**CLI Option:**
`-ds, --docstring-style [reStructuredText|NumPy|Google|Accessible|Blank]`

### RelativeImports

Generate relative instead of absolute imports.

**Default Value:** `False`

**CLI Option:** `--relative-imports / --no-relative-imports`

### CompoundFields

xsdata relies on the field ordering for serialization. This process fails for repeating
choice or complex sequence elements. When you enable compound fields, these elements are
grouped into a single field.

```xml
--8<-- "tests/fixtures/compound/schema.xsd:2:10"
```

**Default Value:** `False`

**CLI Option:** `--compound-fields / --no-compound-fields`

**Sub Settings**

- `defaultName`: The default compound field name, default: `choice`
- `forceDefaultName`: Force the default name in all compound fields, default: `False`
- `useSubstitutionGroups`: When all elements are part of a substitution, use the group
  name as the field name, default: `False`
- `maxNameParts`: The maximum length of elements names allowed before using the default
  name, default: `3`

**Examples:**

```python
# Force default name or max name parts > 3
choice: list[str | int | float | bool] = field(...)

# max name parts <= 3
hat_or_bat_cat: list[str | int | float] = field(...)

# All types belong to the same substitution group `product`
product: list[Shoe | Shirt | Hat] = field(...)
```

### WrapperFields

Generate wrapper fields whenever possible for single or collections of simple and
complex elements.

The wrapper and wrapped elements can't be optional. If the wrapped value is a list it
must have minimum `occurs >= 1`.

```xml
--8<-- "tests/fixtures/wrapper/schema.xsd:2:17"
```

**Default Value:** `False`

**CLI Option:** `--wrapper-fields / --no-wrapper-fields`

**Examples:**

```python
alpha: str = field(
    metadata={
        "wrapper": "alphas",
        "type": "Element",
    },
)
bravo: List[int] = field(
    default_factory=list,
    metadata={
        "wrapper": "bravos",
        "type": "Element",
    },
)
charlie: List[Charlie] = field(
    default_factory=list,
    metadata={
        "wrapper": "charlies",
        "type": "Element",
    },
)
```

### UnnestClasses

The generator creates inner classes for `xs:complexContent`. This option allows to
unnest all inner classes.

**Default Value:** `False`

**CLI Option:** `--unnest-classes / --no-unnest-classes`

### IgnorePatterns

The generator will create a field metadata property for `xs:pattern` elements. This
property is not used during parsing, it's only informative for the developer, if you
want to reduce the noise in the generated code you can enable this option.

**Default Value:** `False`

**CLI Option:** `--ignore-patterns / --no-ignore-patterns`

### IncludeHeader

The generator will add a module docstring in all the output files.

**Example**

```python
"""This file was generated by docx4j-xsdata, v24.1, on 2024-01-22 10:20:25

Generator: DataclassGenerator
See: https://xsdata.readthedocs.io/
"""
```

**Default Value:** `False`

**CLI Option:** `--include-header / --no-include-header`

### AllOptional

!!! Info "docx4j fork option, it does not exist upstream."

Generate every element and attribute field as `None | T` with `default=None`, whatever
the schema's `minOccurs` or `use="required"` says, so that no schema member is a
mandatory keyword argument.

Real world documents are not always schema valid: a Word `w:tbl` may have no
`w:tblGrid`, and a binding that refuses to build the object cannot load the document at
all.

```xml
<Output>
  <AllOptional>true</AllOptional>
</Output>
```

Not affected: list, token list and `xs:anyAttribute` fields, which keep their default
factory; `fixed` value and prohibited attrs, which have no constructor argument to
relax; text/value, wildcard and compound fields, which only become optional when they
would otherwise be required with no default.

A schema declared default value is kept, see [SchemaDefaults](#schemadefaults) for
moving it out of the field.

**Default Value:** `False`

**CLI Option:** none, project configuration only

### SchemaDefaults

!!! Info "docx4j fork option, it does not exist upstream."

Where a schema declared default value ends up.

| Value | Behaviour |
| --- | --- |
| `field` | the dataclass field default, upstream behaviour |
| `metadata` | `default=None` on the field, the schema default under the `schema_default` metadata key |

```xml
<Output>
  <SchemaDefaults>metadata</SchemaDefaults>
</Output>
```

With `field`, the serializer writes every non-None field, so an attribute the source
document never had is invented on output;
`SerializerConfig(ignore_default_attributes=True)` removes those but also drops the
attributes that really were present and happen to equal the default, because the
dataclass cannot tell "absent" from "present and equal to the default".

With `metadata` the field is `None | T` with `default=None`, so absent stays absent and
present stays present, and nothing is lost: the schema default is on the field metadata
and on the runtime binding metadata as `XmlVar.schema_default`, for a resolver to
consult. The parser never fills the field with it.

```python
locked: None | bool = field(
    default=None,
    metadata={
        "type": "Attribute",
        "schema_default": "true",
    },
)
```

The value is the schema's lexical default string. For a field whose type is a generated
enumeration it is the enum member itself, so the reference to the class is not lost.

`fixed` value attrs are not affected: they are generated with `init=False` and the field
is the only place the value lives.

**Default Value:** `field`

**CLI Option:** none, project configuration only

### ListFactory

!!! Info "docx4j fork option, it does not exist upstream."

The dotted path of a list subclass to use as the `default_factory` of every list field.
The class is imported into each generated module that needs it. Unset, the default, means
the builtin `list`.

```xml
<Output>
  <ListFactory>docx4j_py.child.ChildList</ListFactory>
</Output>
```

```python
from docx4j_py.child import ChildList

content: list[P | Tbl] = field(
    default_factory=ChildList,
    metadata={...},
)
```

This is the xsdata equivalent of docx4j's one JAXB customization,
`<jaxb:globalBindings collectionType="org.docx4j.list.ArrayListDocx4j"/>`: a list that
sets the parent pointer of everything appended to it, so that a tree stays navigable
upwards after it is mutated.

Token list (`xs:NMTOKENS` and friends) and `xs:anyAttribute` fields are not affected:
they hold strings, not model objects.

The option is ignored when the output format is `frozen`, where the collections are
tuples.

**Default Value:** unset

**CLI Option:** none, project configuration only

### DeferredImports

!!! Info "docx4j fork option, it does not exist upstream."

Import the classes a module only needs once its own classes exist at the bottom of the
module rather than the top, so that modules which depend on each other can be imported.

```xml
<Output>
  <DeferredImports>true</DeferredImports>
</Output>
```

`--structure-style namespaces` puts one module per target namespace, and a schema set
whose namespaces reference each other in both directions then produces modules that
import each other. ECMA-376 is such a set: WordprocessingML embeds DrawingML and
DrawingML embeds WordprocessingML through `a:graphicData`, and the generated package
cannot be imported at all.

Postponed annotations already make the type hints strings, so the only names a module
needs while its classes are being created are its base classes, the values it puts in
`default=` and the members of its enumerations. Everything else moves below the classes,
and the `choices` metadata of compound fields holds `ForwardRef("Name")` rather than the
class object, which the runtime resolves when it builds the binding metadata.

Two more things follow from it:

* A package `__init__` resolves its re-exports through a module `__getattr__` instead of
  importing them, so touching one module of a package no longer forces its siblings.
* The output root package gets an import order manifest: the strongly connected
  components of the module graph in dependency order, each sorted by its top imports.
  Python initializes a parent package before any of its submodules, so it runs whatever
  the entry point into the package is.

The option is not a cure for a cycle of base classes, which is a real cycle, but there is
no such cycle in ECMA-376.

**Default Value:** `False`

**CLI Option:** none, project configuration only

## Convention Settings

Apply different naming convention per identifier.

| Element        | Default Case         | Default Safe Prefix |
| -------------- | -------------------- | ------------------- |
| `ClassName`    | `pascalCase`         | `type`              |
| `FieldName`    | `snakeCase`          | `value`             |
| `ConstantName` | `screamingSnakeCase` | `value`             |
| `ModuleName`   | `snakeCase`          | `mod`               |
| `PackageName`  | `snakeCase`          | `pkg`               |

**Attributes**

- `case`: The naming class to apply
- `safePrefix`: A prefix to add when the output name is reserved

**Cases**

| Case                 | Input     | Output    |
| -------------------- | --------- | --------- |
| `originalCase`       | `aBBc`    | `aBBc`    |
| `pascalCase`         | `my_type` | `MyType`  |
| `camelCase`          | `my_type` | `myType`  |
| `snakeCase`          | `MyType`  | `my_type` |
| `screamingSnakeCase` | `MyType`  | `My_Type` |
| `mixedCase`          | `MY_TyPE` | `MYTyPE`  |
| `mixedSnakeCase`     | `MyType`  | `My_Type` |
| `mixedPascalCase`    | `my_TYPE` | `MyTYPE`  |

## Substitution Settings

A list of search and replace patterns for identifier names, the substitutions run
**before** and **after** the naming conventions.

**Attributes**

- `type`: The identifier type `[class|field|module|package]`
- `search`: Search Pattern
- `replace`: Replace Pattern

**Defaults**

```xml
<Substitutions>
    <Substitution type="package" search="http://www.w3.org/2001/XMLSchema" replace="xs"/>
    <Substitution type="package" search="http://www.w3.org/XML/1998/namespace" replace="xml"/>
    <Substitution type="package" search="http://www.w3.org/2001/XMLSchema-instance" replace="xsi"/>
    <Substitution type="package" search="http://www.w3.org/1998/Math/MathML" replace="mathml3"/>
    <Substitution type="package" search="http://www.w3.org/1999/xlink" replace="xlink"/>
    <Substitution type="package" search="http://www.w3.org/1999/xhtml" replace="xhtml"/>
    <Substitution type="package" search="http://schemas.xmlsoap.org/wsdl/soap/" replace="soap"/>
    <Substitution type="package" search="http://schemas.xmlsoap.org/wsdl/soap12/" replace="soap12"/>
    <Substitution type="package" search="http://schemas.xmlsoap.org/soap/envelope/" replace="soapenv"/>
    <Substitution type="class" search="(.*)Class$" replace="\1Type"/>
</Substitutions>
```

## Extension Settings

Though extensions you can add base classes, mixins or decorators to the generated
classes. This way you can enhance the models functionality and add any custom business
logic.

The following configuration will add a base class and a decorator to all the generated
classes.

**Attributes**

- `type`: The extension type `[class|decorator]`
- `class`: The class name search pattern
- `import`: The absolute import of the base class or decorator object
- `prepend` Specify if you want the base class or decorator to added before all other
- `apply_if_derived` Specify if you want to add the extension if the class already
  extends another class.
- `module` Optional pattern to match against the fully-qualified parent element's name

!!! Warning

    If there are two extensions of the same type for the same class with the `prepend==True`,
    the base classes or decorators are added in the reverse order they are defined in the
    configuration.

**Example:**

```xml
<Extensions>
    <Extension type="class" class=".*" import="dataclasses_jsonschema.JsonSchemaMixin" prepend="false" applyIfDerived="false"/>
    <Extension type="decorator" class=".*" module="Ancestor\..*\.Papa$" import="typed_dataclass.typed_dataclass" prepend="false" applyIfDerived="false"/>
</Extensions>
```

```python
from dataclasses import dataclass
from dataclasses_jsonschema import JsonSchemaMixin
from typed_dataclass import typed_dataclass

@dataclass
@typed_dataclass
class Cores(JsonSchemaMixin):
    ...
```
