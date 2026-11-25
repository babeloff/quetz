from setuptools import setup

setup(
    name="quetz-harvester",
    install_requires=["libcflib"],
    entry_points={
        "quetz.jobs": ["quetz-harvester=quetz_harvester.jobs"],
    },
    packages=["quetz_harvester"],
)
