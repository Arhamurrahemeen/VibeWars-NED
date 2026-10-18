try:
    import resource
except ImportError:
    resource = None

RESOURCE_LIMITS_AVAILABLE = resource is not None

def apply_limits(cpu_seconds: int, mem_bytes: int):
    if resource is None:
        return False
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    return True
