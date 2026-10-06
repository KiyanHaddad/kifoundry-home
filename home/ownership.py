"""One cooperating server per data directory; no stored-PID termination."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import BinaryIO, Self


class DataOwner:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.file: BinaryIO = (directory / "server.lock").open("a+b")
        try:
            self.file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Reading a byte held by another Windows owner itself fails. Acquire
            # the lock first; byte-range locks can extend beyond the file end.
            if os.fstat(self.file.fileno()).st_size == 0:
                self.file.write(b"0")
                self.file.flush()
        except OSError as error:
            self.file.close()
            raise RuntimeError("This data directory already has an active Home server") from error

    def close(self) -> None:
        if self.file.closed:
            return
        self.file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
