"""Root shim — executed by Hermes' plugin loader (spec_from_file_location with
submodule_search_locations) which imports this directory as ``hermes_plugins.<key>``.
Relative imports resolve within that package namespace; ``usage_footer`` is a plain
subdirectory and works under any import mode (including pytest 9's importlib default).
"""

from .usage_footer.plugin import register

__all__ = ["register"]
