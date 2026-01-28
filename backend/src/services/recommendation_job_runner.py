"""
Recommendation Job Runner.

Processes queued recommendation jobs, generating recommendations
from insights and updating job status.

SECURITY:
- Tenant isolation in all operations
- No external API calls
- No data modifications beyond recommendations

NO AUTO-EXECUTION:
- All recommendations are advisory only

Story 8.3 - AI Recommendations (No Actions)
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from src.models.recommendation_job import (
    RecommendationJob,
    RecommendationJobStatus,
)
from src.services.recommendation_generation_service import RecommendationGenerationService


logger = logging.getLogger(__name__)


class RecommendationJobRunner:
    """
    Runner for recommendation generation jobs.

    Processes queued jobs by:
    1. Marking job as running
    2. Generating recommendations from insights
    3. Updating job status (success/failed)

    SECURITY: tenant_id from job, originally from JWT.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def execute_job(self, job: RecommendationJob) -> bool:
        """
        Execute a single recommendation job.

        Args:
            job: RecommendationJob to execute

        Returns:
            True if job succeeded, False if failed
        """
        logger.info(
            "Starting recommendation job",
            extra={
                "tenant_id": job.tenant_id,
                "job_id": job.job_id,
                "cadence": job.cadence.value if job.cadence else None,
            },
        )

        # Mark as running
        job.mark_running()
        self.db.commit()

        try:
            # Generate recommendations
            service = RecommendationGenerationService(
                db_session=self.db,
                tenant_id=job.tenant_id,
            )

            recommendations, insights_processed = service.generate_recommendations(
                job_id=job.job_id,
            )

            # Mark success
            job.mark_success(
                recommendations_generated=len(recommendations),
                insights_processed=insights_processed,
                metadata={
                    "recommendation_types": list(set(
                        r.recommendation_type.value for r in recommendations
                    )),
                },
            )
            self.db.commit()

            logger.info(
                "Recommendation job completed successfully",
                extra={
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "recommendations_generated": len(recommendations),
                    "insights_processed": insights_processed,
                },
            )

            return True

        except Exception as e:
            logger.error(
                "Recommendation job failed",
                extra={
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            job.mark_failed(str(e))
            self.db.commit()

            return False

    def process_queued_jobs(self, limit: int = 10) -> int:
        """
        Process queued recommendation jobs.

        Args:
            limit: Maximum number of jobs to process

        Returns:
            Number of jobs processed
        """
        queued_jobs = (
            self.db.query(RecommendationJob)
            .filter(RecommendationJob.status == RecommendationJobStatus.QUEUED)
            .order_by(RecommendationJob.created_at.asc())
            .limit(limit)
            .all()
        )

        if not queued_jobs:
            logger.debug("No queued recommendation jobs to process")
            return 0

        processed = 0
        for job in queued_jobs:
            self.execute_job(job)
            processed += 1

        logger.info(
            "Recommendation job processing cycle complete",
            extra={"jobs_processed": processed},
        )

        return processed


def run_recommendation_worker_cycle(db_session: Session) -> int:
    """
    Run a single cycle of the recommendation worker.

    Called by background worker process. Processes up to 10 queued jobs.

    Args:
        db_session: Database session

    Returns:
        Number of jobs processed
    """
    runner = RecommendationJobRunner(db_session)
    return runner.process_queued_jobs(limit=10)
