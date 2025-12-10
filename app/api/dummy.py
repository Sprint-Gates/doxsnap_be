from fastapi import APIRouter

router = APIRouter()


@router.get("/dummy")
def test():
    return "test"