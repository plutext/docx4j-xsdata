import sys


def main() -> None:
    """Cli entry point."""
    try:
        from docx4j_xsdata.cli import cli

        cli()
    except ImportError:
        print('Install cli requirements "pip install docx4j-xsdata[cli]"')
        sys.exit(1)


if __name__ == "__main__":
    main()
