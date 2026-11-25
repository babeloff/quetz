from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .rest_models import SolveTask
from .solver import PixiSolver
from .utils import timed_lru_cache

router = APIRouter()


@timed_lru_cache(hours=3, maxsize=128)
def get_solver(channels, subdir):
    s = PixiSolver(list(channels), subdir)
    return s


@router.post("/api/mamba/solve", response_class=PlainTextResponse)
def mamba_solve(solve_task: SolveTask):
    channels = tuple(solve_task.channels)
    subdir = solve_task.subdir
    spec = solve_task.spec

    s = get_solver(channels, subdir)
    try:
        return s.solve(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
