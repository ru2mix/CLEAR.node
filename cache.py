import time
from threading import Lock

class TTLCache:
    def __init__(self, ttl=60): 
        self.ttl = ttl
        self.cache = {}
        self.lock = Lock() 

    def get(self, key):
        with self.lock:
            if key in self.cache:
                val, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return val
                else:
                    del self.cache[key]
                    return None
            return None

    def set(self, key, value):
        with self.lock:
            self.cache[key] = (value, time.time())

    def delete(self, key):
        with self.lock:
            if key in self.cache:
                del self.cache[key]

    def clear(self):
        with self.lock:
            self.cache.clear()


auth_cache = TTLCache(ttl=3600)           
rights_cache = TTLCache(ttl=300)         
accessible_ids_cache = TTLCache(ttl=300) 
groups_cache = TTLCache(ttl=300)        
workspace_key_cache = TTLCache(ttl=300) 
users_cache = TTLCache(ttl=300)          
pending_cache = TTLCache(ttl=300)        
tokens_cache = TTLCache(ttl=300)        
settings_cache = TTLCache(ttl=300)