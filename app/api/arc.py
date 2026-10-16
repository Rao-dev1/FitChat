from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import arc as arc_svc
from ..services import nudges as nd

router = APIRouter(prefix="/api", tags=["arc"])


@router.get("/arc")
def arc(db: Session = Depends(get_db)):
    return arc_svc.status(db)


@router.get("/nudges")
def nudges(db: Session = Depends(get_db)):
    return {"nudges": nd.compute(db), "kinds": nd.KINDS}
