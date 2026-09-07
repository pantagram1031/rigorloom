export type RuntimeUnlisten = () => void;

/** Own asynchronous listener registrations for one React effect lifetime. */
export class RuntimeSubscriptionScope {
  private disposed = false;
  private readonly unlisteners = new Set<RuntimeUnlisten>();

  get isDisposed(): boolean {
    return this.disposed;
  }

  async add(registration: Promise<RuntimeUnlisten>): Promise<boolean> {
    const unlisten = await registration;
    if (this.disposed) {
      try {
        unlisten();
      } catch {
        // Cleanup is best-effort; one listener must not strand the others.
      }
      return false;
    }
    this.unlisteners.add(unlisten);
    return true;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const unlisten of this.unlisteners) {
      try {
        unlisten();
      } catch {
        // Keep draining the owned registrations.
      }
    }
    this.unlisteners.clear();
  }
}
