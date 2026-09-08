from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def upgrade_schema() -> None:
    command.upgrade(alembic_config(), "head")


def check_schema() -> None:
    command.check(alembic_config())
