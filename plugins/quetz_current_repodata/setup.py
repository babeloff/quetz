from setuptools import setup

setup(
    name="quetz-current_repodata",
    python_requires=">=3.11",
    install_requires=["py-rattler>=0.29,<0.30"],
    entry_points={"quetz": ["quetz-current_repodata = quetz_current_repodata.main"]},
    packages=["quetz_current_repodata"],
)
