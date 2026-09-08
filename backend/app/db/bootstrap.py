from app.db.alembic_runtime import upgrade_schema


def main() -> None:
    upgrade_schema()


if __name__ == "__main__":
    main()
