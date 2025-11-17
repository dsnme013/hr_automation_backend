import logging
from flask_caching import Cache
from concurrent.futures import ThreadPoolExecutor

cache = Cache(config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})
logger = logging.getLogger("talentflow")
logger.setLevel(logging.INFO)
executor = ThreadPoolExecutor(max_workers=4)
