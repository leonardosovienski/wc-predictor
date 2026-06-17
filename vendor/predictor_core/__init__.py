"""predictor-core — biblioteca vendorizada. NÃO editar local; sync via script."""
import pathlib

VERSION_FILE = pathlib.Path(__file__).parent / "VERSION"
__version__ = VERSION_FILE.read_text(encoding="utf-8").strip().split("\n")[0]
