export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public uncertain = false,
  ) {
    super(
      uncertain
        ? `${code}: outcome unknown. Reconcile server state before another attempt.`
        : code.replaceAll('_', ' '),
    );
    this.name = 'ApiError';
  }
}
