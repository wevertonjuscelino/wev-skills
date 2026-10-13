"""Which remote runs a wev run started, kept in that run's own state.

``status`` needs evidence that does not come from the host: once a session is gone, an
exit file there proves nothing by itself, because anything on the host can write one. A
start recorded in the run state is that evidence. Nothing is sent anywhere. Without an
active run there is no run state, so nothing is recorded and no exit file is trusted
after its session has ended.
"""

from __future__ import annotations

from wev_skills.remote.session import RemoteRun
from wev_skills.state.model import with_remote_run
from wev_skills.state.records import RemoteRunRecord
from wev_skills.state.store import StateStore


class StateRunRecords:
    """``RunRecords`` over ``RunState.remote_runs``: one record per task and host.

    Writes go through ``StateStore.update``, so they are conditional on the revision on
    disk and serialized by the state lock; a state that cannot be read raises a ``WevError``.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def record(self, run: RemoteRun) -> None:
        """Store ``run``, replacing an earlier start of the same task on the same host."""
        record = RemoteRunRecord.from_dict(run.to_dict())
        self._store.update(lambda state: with_remote_run(state, record))

    def find(self, task_id: str, alias: str) -> RemoteRun | None:
        for item in self._store.load().remote_runs:
            if (item.task_id, item.alias) == (task_id, alias):
                return RemoteRun.from_dict(item.to_dict())
        return None
