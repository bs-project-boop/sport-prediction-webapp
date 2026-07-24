#!/usr/bin/env python3
"""Lock wrapper: run a command only if no other instance holds the lock.
   
Usage: python3 sport-lock-wrapper.py <lockfile> <command...>
   
   If lock is held by another PID, exits 0 silently.
   If lock acquired, runs command and releases lock on exit.
"""
import os
import sys
import fcntl
import subprocess
import pathlib

def main():
    if len(sys.argv) < 3:
        print("Usage: sport-lock-wrapper.py <lockfile> <cmd...>", file=sys.stderr)
        sys.exit(1)
    
    lockfile = pathlib.Path(sys.argv[1]).resolve()
    cmd = sys.argv[2:]
    
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        fd = os.open(str(lockfile), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        # Lock held by another process — skip silently
        sys.exit(0)
    
    # Write our PID
    os.write(fd, f"{os.getpid()}\n".encode())
    os.ftruncate(fd, os.fstat(fd).st_size)
    
    # Run the command
    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        try:
            lockfile.unlink()
        except FileNotFoundError:
            pass

if __name__ == "__main__":
    main()
