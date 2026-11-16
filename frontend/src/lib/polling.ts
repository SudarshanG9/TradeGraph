/** One resource generation: completion-based scheduling, capped backoff and abort cleanup. */
export function startPolling<T>(options: {
  load: (signal: AbortSignal) => Promise<T>;
  value: (value: T) => void;
  error: (error: unknown) => void;
  settled: () => void;
  interval: number;
  hidden: () => boolean;
  enabled: boolean;
}) {
  const controller = new AbortController();
  let stopped = false,
    pending = false,
    failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const run = async () => {
    if (stopped || pending || !options.enabled || options.interval < 0) return;
    if (options.hidden()) {
      timer = setTimeout(run, Math.max(options.interval, 1000));
      return;
    }
    pending = true;
    try {
      const result = await options.load(controller.signal);
      if (!stopped) {
        options.value(result);
        failures = 0;
      }
    } catch (e) {
      if (!stopped) {
        failures++;
        options.error(e);
      }
    } finally {
      pending = false;
      if (!stopped) {
        options.settled();
        if (options.interval > 0)
          timer = setTimeout(run, Math.min(options.interval * 2 ** Math.min(failures, 4), 30000));
      }
    }
  };
  void run();
  return {
    refresh: () => {
      clearTimeout(timer);
      void run();
    },
    stop: () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    },
  };
}
