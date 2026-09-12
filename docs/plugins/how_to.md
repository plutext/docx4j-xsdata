# How to extend xsdata

There are two main entrypoints that developers can leverage to add support a new
generator output or/and a new class type for data bindings.

## `docx4j_xsdata.plugins.cli`

This entrypoint allows developers to register a new
[docx4j_xsdata.formats.mixins.AbstractGenerator][].

```python
from docx4j_xsdata.codegen.writer import CodeWriter
from docx4j_xsdata.formats.mixins import AbstractGenerator

class AwesomeGenerator(AbstractGenerator):
    ...

CodeWriter.register_generator("awesome", AwesomeGenerator)
```

Which can be used during code generation.

```console
$ docx4j-xsdata generate --output awesome
```

## `docx4j_xsdata.plugins.class_types`

This entrypoint can be used to register a new
[docx4j_xsdata.formats.dataclass.compat.ClassType][] for binding operations.

```python
from docx4j_xsdata.formats.dataclass.compat import class_types
from docx4j_xsdata.formats.dataclass.compat import ClassType

class AwesomeType(ClassType):
    ...

class_types.register("awesome", AwesomeType())
```

Which then can be used like this:

```python
from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser

context = XmlContext(class_types="awesome")
parser = XmlParser(context=context)
```
