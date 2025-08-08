from importlib.metadata import version, PackageNotFoundError

try:
    version = version("ordec")
except PackageNotFoundError:
    version = 'unknown'
