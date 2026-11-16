/** Completion-based polling with one coalesced trailing refresh and scope abort. */
export function startPolling<T>(options: {
  load: (signal: AbortSignal) => Promise<T>;
  value: (value: T) => void;
  error: (error: unknown) => void;
  settled: () => void;
  started?: () => void;
  interval: number;
  hidden: () => boolean;
  enabled: boolean;
}) {
  const controller = new AbortController();
  let stopped = false,
    pending = false,
    queued = false,
    failures = 0;
  let waiting: ((success: boolean) => void)[] = [];
  let current: ((success: boolean) => void)[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;
  const run = async () => {
    if (stopped || pending || !options.enabled || options.interval < 0) return;
    clearTimeout(timer);
    if (options.hidden()) {
      waiting.splice(0).forEach((resolve) => resolve(false));
      timer = setTimeout(run, Math.max(options.interval, 1000));
      return;
    }
    pending = true;
    queued = false;
    current = waiting.splice(0);
    options.started?.();
    let success = false;
    try {
      const result = await options.load(controller.signal);
      if (!stopped) {
        options.value(result);
        failures = 0;
        success = true;
      }
    } catch (error) {
      if (!stopped) {
        failures++;
        options.error(error);
      }
    } finally {
      pending = false;
      current.splice(0).forEach((resolve) => resolve(success));
      if (!stopped) {
        options.settled();
        if (queued) void run();
        else if (options.interval > 0)
          timer = setTimeout(run, Math.min(options.interval * 2 ** Math.min(failures, 4), 30000));
      }
    }
  };
  void run();
  return {
    refresh: (): Promise<boolean> => {
      if (stopped || !options.enabled || options.interval < 0) return Promise.resolve(false);
      clearTimeout(timer);
      const completion = new Promise<boolean>((resolve) => waiting.push(resolve));
      if (pending) queued = true;
      else void run();
      return completion;
    },
    stop: () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      [...current.splice(0), ...waiting.splice(0)].forEach((resolve) => resolve(false));
    },
  };
}
