# tag::ci-services[]
"""Start or stop the Podman services used by integration tests."""

import argparse
import subprocess
import time

SERVICES = ("quetz-ci-postgres", "quetz-ci-redis")


def start():
    subprocess.run(
        [
            "podman",
            "run",
            "-d",
            "--name",
            SERVICES[0],
            "-e",
            "POSTGRES_PASSWORD=mysecretpassword",
            "-e",
            "POSTGRES_DB=postgres",
            "-p",
            "127.0.0.1:5432:5432",
            "--health-cmd",
            "pg_isready",
            "--health-interval",
            "2s",
            "--health-retries",
            "30",
            "docker.io/library/postgres:16",
        ],
        check=True,
    )
    subprocess.run(
        [
            "podman",
            "run",
            "-d",
            "--name",
            SERVICES[1],
            "-p",
            "127.0.0.1:6379:6379",
            "--health-cmd",
            "redis-cli ping",
            "--health-interval",
            "2s",
            "--health-retries",
            "30",
            "docker.io/library/redis:7",
        ],
        check=True,
    )
    for service in SERVICES:
        for _ in range(60):
            result = subprocess.run(
                ["podman", "inspect", "--format", "{{.State.Health.Status}}", service],
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "healthy":
                break
            time.sleep(1)
        else:
            subprocess.run(["podman", "logs", service], check=False)
            raise RuntimeError(f"Service did not become healthy: {service}")


def stop():
    subprocess.run(["podman", "rm", "-f", "--ignore", *SERVICES], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"], default="start", nargs="?")
    args = parser.parse_args()
    if args.action == "start":
        start()
    else:
        stop()
# end::ci-services[]
