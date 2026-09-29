"""
Wipe the database and rebuild it from the current models, then reseed the
sample teachers. Use this after upgrading to a version whose tables changed
(the API will tell you when it needs this).

    python -m app.reset_db          # asks for confirmation
    python -m app.reset_db --yes    # no prompt
    python -m app.reset_db --no-seed
"""
import argparse
import sys

from . import models  # noqa: F401  (registers every table on Base.metadata)
from . import seed
from .database import Base, engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--no-seed", action="store_true", help="don't load sample teachers")
    args = parser.parse_args()

    target = engine.url.render_as_string(hide_password=True)
    if not args.yes:
        print(f"This will DELETE ALL DATA in:\n  {target}")
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("Cancelled - nothing was changed.")
            return 1

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Database rebuilt.")
    if not args.no_seed:
        seed.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
