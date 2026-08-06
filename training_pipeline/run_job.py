"""Manually advance a training job through available pipeline stages. v1: run by hand; a background worker/scheduler is a v2 upgrade."""
import sys
sys.path.insert(0, '.')
from db.session import SessionLocal
from db.models import TrainingJob
from training_pipeline.data_acquisition import run_for_job as acquire_step
from training_pipeline.dataset_prep import run_for_job as prep_step
from training_pipeline.train import run_for_job as train_step
from training_pipeline.evaluate import run_for_job as eval_step

job_id = int(sys.argv[1])
epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 10
db = SessionLocal()
try:
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        print(f"Job {job_id} not found")
    else:
        if job.current_stage in ("queued", None) or job.status == "pending":
            acquire_step(job_id, db, TrainingJob)
            db.refresh(job)
        if job.status != "failed" and job.current_stage == "preparing_dataset":
            prep_step(job_id, db, TrainingJob)
            db.refresh(job)
        if job.status != "failed" and job.current_stage == "training":
            train_step(job_id, db, TrainingJob, epochs=epochs)
            db.refresh(job)
        if job.status != "failed" and job.current_stage == "evaluating":
            eval_step(job_id, db, TrainingJob)
            db.refresh(job)
        print(f"Job {job_id} now at stage '{job.current_stage}', status '{job.status}'")
finally:
    db.close()