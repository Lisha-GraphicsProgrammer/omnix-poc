"""Manually advance a training job through available pipeline stages, one call per stage present."""
import sys
sys.path.insert(0, '.')
from db.session import SessionLocal
from db.models import TrainingJob
from training_pipeline.data_acquisition import run_for_job as acquire_step
from training_pipeline.dataset_prep import run_for_job as prep_step
from training_pipeline.train import run_for_job as train_step
from training_pipeline.evaluate import run_for_job as eval_step

STAGE_HANDLERS = {
    "queued": acquire_step,
    "searching_data": acquire_step,
    "preparing_dataset": prep_step,
    "training": None,  # handled separately below, needs epochs arg
    "evaluating": eval_step,
}

job_id = int(sys.argv[1])
epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 10
db = SessionLocal()
try:
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        print(f"Job {job_id} not found")
    else:
        stage = job.current_stage or "queued"
        if stage in ("awaiting_approval", "approved"):
            print(f"Job {job_id} is at '{stage}', nothing to run, waiting on human approval")
        elif stage == "training":
            train_step(job_id, db, TrainingJob, epochs=epochs)
            db.refresh(job)
            print(f"Job {job_id} now at stage '{job.current_stage}', status '{job.status}'")
        else:
            handler = STAGE_HANDLERS.get(stage)
            if handler:
                handler(job_id, db, TrainingJob)
                db.refresh(job)
                print(f"Job {job_id} now at stage '{job.current_stage}', status '{job.status}'")
            else:
                print(f"Job {job_id} at unknown stage '{stage}'")
finally:
    db.close()