"""One-off script: create the jobs table if it does not already exist."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.msbc.database.base import Base, engine
import src.msbc.models.entities  # registers RequirementExtraction, FrontendPlan, Job

Base.metadata.create_all(engine)
print("Tables now in DB:", sorted(Base.metadata.tables.keys()))
