from urllib.request import build_opener

from docx4j_xsdata import __version__

opener = build_opener()
opener.addheaders = [("User-agent", f"docx4j-xsdata/{__version__}")]
