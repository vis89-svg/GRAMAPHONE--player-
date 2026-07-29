from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker
from api.dependencies.database import engine
from api.services.playlist_service import run_nightly_playlist_refresh
from api.services.affinity_service import recalculate_affinities, recalculate_taste_profile
from api.models import Profile
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def nightly_job():
    """Run nightly maintenance: recalculate affinities, refresh playlists."""
    logger.info("Starting nightly maintenance job")
    async with async_session() as db:
        try:
            # Get all active profiles (those with listening history in last 30 days)
            from datetime import datetime, timedelta
            from api.models import ListeningHistory
            
            cutoff = datetime.utcnow() - timedelta(days=30)
            profiles_result = await db.execute(
                select(Profile.id)
                .join(ListeningHistory, Profile.id == ListeningHistory.profile_id)
                .where(ListeningHistory.played_at >= cutoff)
                .distinct()
            )
            profile_ids = [r[0] for r in profiles_result.all()]
            
            logger.info(f"Found {len(profile_ids)} active profiles")
            
            for profile_id in profile_ids:
                try:
                    # Recalculate affinities
                    await recalculate_affinities(db, profile_id)
                    await recalculate_taste_profile(db, profile_id)
                    
                    # Generate blueprint
                    from api.services.blueprint_service import blueprint_service
                    await blueprint_service.generate_blueprint(db, profile_id)
                    
                    # Refresh playlists
                    await run_nightly_playlist_refresh(db)
                    
                    await db.commit()
                    logger.info(f"Completed nightly job for profile {profile_id}")
                except Exception as e:
                    logger.error(f"Nightly job failed for profile {profile_id}: {e}")
                    await db.rollback()
                    
        except Exception as e:
            logger.error(f"Nightly job failed: {e}")


async def morning_blueprint_job():
    """Generate blueprints for all active users at 6 AM."""
    logger.info("Starting morning blueprint generation")
    async with async_session() as db:
        try:
            from datetime import datetime, timedelta
            from api.models import ListeningHistory
            
            cutoff = datetime.utcnow() - timedelta(days=7)
            profiles_result = await db.execute(
                select(Profile.id)
                .join(ListeningHistory, Profile.id == ListeningHistory.profile_id)
                .where(ListeningHistory.played_at >= cutoff)
                .distinct()
            )
            profile_ids = [r[0] for r in profiles_result.all()]
            
            logger.info(f"Generating blueprints for {len(profile_ids)} profiles")
            
            from api.services.blueprint_service import blueprint_service
            for profile_id in profile_ids:
                try:
                    await blueprint_service.generate_blueprint(db, profile_id)
                    await db.commit()
                except Exception as e:
                    logger.error(f"Blueprint generation failed for {profile_id}: {e}")
                    await db.rollback()
                    
        except Exception as e:
            logger.error(f"Morning blueprint job failed: {e}")


def start_scheduler():
    """Start the APScheduler with configured jobs."""
    # Nightly at 3 AM
    scheduler.add_job(
        nightly_job,
        CronTrigger(hour=3, minute=0),
        id="nightly_maintenance",
        replace_existing=True
    )
    
    # Morning blueprint at 6 AM
    scheduler.add_job(
        morning_blueprint_job,
        CronTrigger(hour=6, minute=0),
        id="morning_blueprints",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started with nightly and morning jobs")


def shutdown_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler shut down")