from .cli import main

# Guard je nutný: analýza běží ve více procesech a na Windows by je jinak spustila znovu.
if __name__ == "__main__":
    raise SystemExit(main())
