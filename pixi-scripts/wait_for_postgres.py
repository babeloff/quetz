# tag::wait-for-postgres[]
"""Wait for PostgreSQL, then optionally replace this process with a command."""

import argparse
import os
import subprocess
import time


def wait_and_exec(host, command):
    env = {**os.environ, "PGPASSWORD": os.environ["POSTGRES_PASSWORD"]}
    while subprocess.run(
        ["psql", "-h", host, "-U", "postgres", "-c", "\\q"], env=env, check=False
    ).returncode:
        print("Postgres is unavailable - sleeping", flush=True)
        time.sleep(1)
    if command:
        os.execvp(command[0], command)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    wait_and_exec(args.host, args.command)
# end::wait-for-postgres[]
