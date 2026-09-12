# Installation

## Using pip

```console
pip install docx4j-xsdata[cli,lxml,soap]
```

!!! hint

    - Install the cli requirements for the code generator
    - Install the soap requirements for the builtin wsdl client
    - Install lxml for enhanced performance and advanced features

## From repository

```console
pip install docx4j-xsdata[cli,lxml] @ git+https://github.com/plutext/docx4j-xsdata
```

## Verify installation

Verify installation using the cli entry point.

```console exec="1" source="console"
$ docx4j-xsdata --help
```

## Requirements

!!! Note "xsData relies on these awesome libraries and supports `python >= 3.10`"

    - [lxml](https://lxml.de/) - XML advanced features
    - [requests](https://requests.readthedocs.io/) - Webservice Default Transport
    - [click](https://click.palletsprojects.com/) - CLI entry point
    - [toposort](https://pypi.org/project/toposort/) - Resolve class ordering
    - [jinja2](https://jinja.palletsprojects.com/) - Code generation
    - [ruff](https://pypi.org/project/ruff/) - Code formatting
