import time


class MetricsAggregator:
    def __init__(self):
        self.timings = {}
        self.counts = {}

    def start_timer(self, key):
        self.timings[key] = self.timings.get(key, [])
        self.timings[key].append(-time.time())

    def stop_timer(self, key):
        self.timings[key][-1] += time.time()

    def increment_count(self, key, count=1):
        if key not in self.counts:
            self.counts[key] = 0
        self.counts[key] += count

    def get_timing_stats(self, key):
        times = self.timings.get(key, [])
        if not times:
            return None
        return {
            "count": len(times),
            "total": sum(times),
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
        }

    def get_count(self, key):
        return self.counts.get(key, 0)

    def report(self):
        report = {}
        for key, times in self.timings.items():
            report[key] = self.get_timing_stats(key)
        for key, count in self.counts.items():
            report[f"{key}_count"] = count
        return report


# metrics = MetricsAggregator()

# # Example of timing a code section
# metrics.start_timer('process_data')
# # Simulate data processing
# time.sleep(0.5)
# metrics.stop_timer('process_data')

# # Counting occurrences
# metrics.increment_count('api_calls')
# metrics.increment_count('api_calls')
# metrics.increment_count('api_errors')

# # Getting aggregated results
# print(metrics.report())
