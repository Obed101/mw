import threading
import logging
from flask import current_app
from functools import wraps

logger = logging.getLogger(__name__)

# In-memory set to track running jobs by a unique key (e.g., "shop_1", "product_42")
_running_jobs = set()
_jobs_lock = threading.Lock()

def run_in_background(job_key=None):
    """
    Decorator to run a function in a background thread with Flask app context.
    If job_key is provided, it prevents duplicate jobs from running simultaneously.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            app = current_app._get_current_object()
            
            if job_key:
                # Evaluate job_key if it's a string with placeholders (simple implementation)
                # For more complex cases, the function should handle locking internally
                with _jobs_lock:
                    if job_key in _running_jobs:
                        logger.warning(f"Job {job_key} is already running. Skipping.")
                        return
                    _running_jobs.add(job_key)

            def thread_function(app_context, *t_args, **t_kwargs):
                try:
                    with app_context:
                        f(*t_args, **t_kwargs)
                except Exception as e:
                    logger.error(f"Background thread error in {f.__name__}: {str(e)}", exc_info=True)
                finally:
                    if job_key:
                        with _jobs_lock:
                            _running_jobs.discard(job_key)

            thread = threading.Thread(
                target=thread_function,
                args=(app.app_context(), *args),
                kwargs=kwargs
            )
            thread.daemon = True
            thread.start()
            logger.info(f"Started background thread for {f.__name__}")
            return thread
            
        return wrapper
    return decorator

def is_job_running(job_key):
    with _jobs_lock:
        return job_key in _running_jobs
