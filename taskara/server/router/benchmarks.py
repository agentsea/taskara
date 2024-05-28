import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from taskara.auth.transport import get_user_dependency
from taskara.benchmark import Benchmark, Eval
from taskara.server.models import (
    V1Benchmark,
    V1BenchmarkEval,
    V1Benchmarks,
    V1Eval,
    V1Evals,
    V1UserProfile,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/v1/benchmarks", response_model=V1Benchmark)
async def create_benchmark(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    data: V1Benchmark,
):
    logger.debug(f"Creating benchmark with model: {data}")
    benchmark = Benchmark.from_v1(data, owner_id=current_user.email)
    benchmark.save()
    return benchmark.to_v1()


@router.get("/v1/benchmarks", response_model=V1Benchmarks)
async def get_benchmarks(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())]
):
    benchmarks = Benchmark.find(owner_id=current_user.email)
    return V1Benchmarks(benchmarks=[benchmark.to_v1() for benchmark in benchmarks])


@router.get("/v1/benchmarks/{id}", response_model=V1Benchmark)
async def get_benchmark(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    id: str,
):
    logger.debug(f"Finding benchmark by id: {id}")
    benchmarks = Benchmark.find(id=id, owner_id=current_user.email)
    if not benchmarks:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return benchmarks[0].to_v1()


@router.delete("/v1/benchmarks/{id}")
async def delete_benchmark(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    id: str,
):
    Benchmark.delete(id=id, owner_id=current_user.email)  # type: ignore
    return {"message": "Benchmark deleted successfully"}


@router.post("/v1/benchmarks/{id}/eval", response_model=V1Eval)
async def create_eval_from_benchmark(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    id: str,
    data: V1BenchmarkEval,
):
    logger.debug(f"Finding benchmark by id: {id}")
    benchmarks = Benchmark.find(id=id, owner_id=current_user.email)
    if not benchmarks:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    benchmark = benchmarks[0]

    eval = benchmark.eval(
        data.assigned_to, data.assigned_type, owner_id=current_user.email
    )
    eval.save()
    return eval.to_v1()


@router.post("/v1/evals", response_model=V1Eval)
async def create_eval(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    data: V1Eval,
):
    logger.debug(f"Creating eval with model: {data}")
    eval_instance = Eval.from_v1(data, owner_id=current_user.email)
    eval_instance.save()
    return eval_instance.to_v1()


@router.get("/v1/evals", response_model=V1Evals)
async def get_evals(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())]
):
    evals = Eval.find(owner_id=current_user.email)
    return V1Evals(evals=[eval_instance.to_v1() for eval_instance in evals])


@router.get("/v1/evals/{id}", response_model=V1Eval)
async def get_eval(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    id: str,
):
    logger.debug(f"Finding eval by id: {id}")
    evals = Eval.find(id=id, owner_id=current_user.email)
    if not evals:
        raise HTTPException(status_code=404, detail="Eval not found")
    return evals[0].to_v1()


@router.delete("/v1/evals/{id}")
async def delete_eval(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    id: str,
):
    Eval.delete(id=id, owner_id=current_user.email)  # type: ignore
    return {"message": "Eval deleted successfully"}
