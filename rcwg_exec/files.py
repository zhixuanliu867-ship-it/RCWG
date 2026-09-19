"""Shared filesystem safety only; no parsing, kernels or oracle logic."""
import os
from pathlib import Path
import stat
from .errors import ExecFault

def open_regular(path):
    """Walk every path component without following links, including ancestors."""
    path=Path(path).absolute()
    descriptor=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd);raise ExecFault('DATA_NOT_REGULAR')
        return fd
    except OSError:
        raise ExecFault('DATA_PATH_UNSAFE') from None
    finally:
        os.close(descriptor)
