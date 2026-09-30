"""The Alembic history stays one linear chain from the baseline.

Two branches that each add a revision would create two heads; ``upgrade head``
then refuses to run and the deployment fails. The database-side check (models vs.
migrated schema) runs in predeploy.sh, which bootstraps a real PostgreSQL.
"""
from alembic.script import ScriptDirectory

from app.db.bootstrap import BASELINE_REVISION, alembic_config


def test_single_linear_history_from_the_baseline() -> None:
    scripts = ScriptDirectory.from_config(alembic_config())
    heads = scripts.get_heads()
    assert len(heads) == 1, f"multiple heads: {heads}"
    chain = list(scripts.walk_revisions(base="base", head=heads[0]))
    assert chain[-1].revision == BASELINE_REVISION
    assert all(len(revision._all_down_revisions) <= 1 for revision in chain)
