"""Sin argumentos abre la GUI; con argumentos usa la CLI."""
import multiprocessing
import sys


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 1 or sys.argv[1:] == ["--gui"]:
        from .gui import main
        main()
    else:
        from .cli import main
        raise SystemExit(main())
