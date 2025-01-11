import redis.asyncio as redis
import os

# Global variable to hold the Redis connection pool and client
# TODO Need to mock redis streams and async functionality or check if Fake Redis supports it
redis_pool: redis.ConnectionPool | None = None
redis_client: redis.Redis | None = None
redis_url = os.environ.get("REDIS_CACHE_STORAGE", None)

# store stream names here
stream_action_recorded = "events:action_recorded"

async def init_redis_pool():
    """Initialize the Redis connection pool."""
    global redis_pool, redis_client
    
    if redis_url:
        # Create a Redis connection pool
        redis_pool = redis.ConnectionPool.from_url(redis_url, max_connections=10)
        print("Redis connection pool initialized.", flush=True)
    else:
        print("No Redis URL", flush=True)

def get_redis_client():
    """Get a Redis client from the connection pool."""
    global redis_pool
    if not redis_pool:
        # TODO need to have proper mocking of redis in order to do this
        # raise ValueError("Redis connection pool is not initialized or redis connection details don't exist. Call init_redis_pool() first.")
        return None
    return redis.Redis(connection_pool=redis_pool)

async def close_redis_pool():
    global redis_pool, redis_client
    if redis_pool:
        await redis_pool.disconnect()
        redis_pool = None
        redis_client = None