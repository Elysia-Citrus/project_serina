"""Reserved storage boundary for future non-memory persistence.

The active SQLite memory store currently lives in ``src.memory.store``. This
module remains as an explicit placeholder so future storage work has a stable
namespace without implying a second runtime database layer today.
"""

__all__: list[str] = []
