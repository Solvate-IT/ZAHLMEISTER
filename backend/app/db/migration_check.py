from app.db.alembic_runtime import check_schema


def main() -> None:
    check_schema()


if __name__ == "__main__":
    main()
