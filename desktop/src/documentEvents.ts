import * as rt from "./runtime";
import { getState, pushEvents, setState } from "./store";
import type { EventDelivery, RuntimeError } from "./types";

interface EventState {
  activeSessionId: string | null;
  eventSubscription: string | null;
}

interface EventOwnerDependencies {
  read: () => EventState;
  patch: (patch: {
    events?: [];
    eventSubscription?: string | null;
    eventPhase?: "starting" | "ready" | "failed";
    eventError?: RuntimeError | null;
  }) => void;
  subscribe: (sessionId: string) => Promise<{ subscriptionId: string }>;
  unsubscribe: (subscriptionId: string) => Promise<unknown>;
  publish: (batch: EventDelivery[]) => void;
  runtimeError: (error: unknown) => RuntimeError;
}

/**
 * Serialises ownership, not transport. Notifications may beat the subscribe
 * response across IPC, so they wait in the request's inbox until its returned
 * subscription id can authenticate them.
 */
export class DocumentEventOwner {
  private generation = 0;
  private installed: { sessionId: string; subscriptionId: string } | null = null;
  private readonly dependencies: EventOwnerDependencies;
  private readonly pendingDeliveryCap = 1000;
  private readonly pending = new Map<
    number,
    { sessionId: string; deliveries: Map<string, EventDelivery[]> }
  >();

  constructor(dependencies: EventOwnerDependencies) {
    this.dependencies = dependencies;
  }

  async start(sessionId: string): Promise<void> {
    if (this.dependencies.read().activeSessionId !== sessionId) return;

    const generation = ++this.generation;
    const previous = this.installed?.subscriptionId ?? this.dependencies.read().eventSubscription;
    this.installed = null;
    this.pending.clear();
    this.pending.set(generation, { sessionId, deliveries: new Map() });
    this.dependencies.patch({
      eventSubscription: null,
      events: [],
      eventPhase: "starting",
      eventError: null,
    });
    if (previous) void this.unsubscribeQuietly(previous);

    try {
      const { subscriptionId } = await this.dependencies.subscribe(sessionId);
      const current =
        generation === this.generation &&
        this.dependencies.read().activeSessionId === sessionId;
      if (!current) {
        this.pending.delete(generation);
        void this.unsubscribeQuietly(subscriptionId);
        return;
      }

      this.installed = { sessionId, subscriptionId };
      this.dependencies.patch({ eventSubscription: subscriptionId, eventPhase: "ready" });
      const buffered =
        this.pending.get(generation)?.deliveries.get(subscriptionId) ?? [];
      this.pending.delete(generation);
      if (buffered.length > 0) this.dependencies.publish(buffered);
    } catch (error) {
      this.pending.delete(generation);
      if (
        generation === this.generation &&
        this.dependencies.read().activeSessionId === sessionId
      ) {
        this.dependencies.patch({
          eventPhase: "failed",
          eventError: this.dependencies.runtimeError(error),
        });
      }
    }
  }

  deliver(batch: EventDelivery[]): void {
    if (batch.length === 0) return;
    if (this.installed) {
      this.dependencies.publish(batch);
      return;
    }

    const pending = this.pending.get(this.generation);
    if (!pending) return;
    for (const delivery of batch) {
      if (delivery.sessionId !== pending.sessionId) continue;
      const deliveries = pending.deliveries.get(delivery.subscriptionId) ?? [];
      deliveries.push(delivery);
      if (deliveries.length > this.pendingDeliveryCap) {
        deliveries.splice(0, deliveries.length - this.pendingDeliveryCap);
      }
      pending.deliveries.set(delivery.subscriptionId, deliveries);
    }
  }

  /** Forget ids owned by a Runtime process that has already exited. */
  forget(): void {
    ++this.generation;
    this.installed = null;
    this.pending.clear();
  }

  stop(): void {
    ++this.generation;
    this.pending.clear();
    const subscriptionId =
      this.installed?.subscriptionId ?? this.dependencies.read().eventSubscription;
    this.installed = null;
    this.dependencies.patch({ eventSubscription: null });
    if (subscriptionId) void this.unsubscribeQuietly(subscriptionId);
  }

  private async unsubscribeQuietly(subscriptionId: string): Promise<void> {
    try {
      await this.dependencies.unsubscribe(subscriptionId);
    } catch {
      // It may already be gone because the Runtime exited or won the race.
    }
  }
}

const owner = new DocumentEventOwner({
  read: getState,
  patch: setState,
  subscribe: (sessionId) => rt.subscribeEvents(sessionId, -1, 250),
  unsubscribe: rt.unsubscribeEvents,
  publish: pushEvents,
  runtimeError: rt.asRuntimeError,
});

export const startDocumentEvents = (sessionId: string) => owner.start(sessionId);
export const deliverDocumentEvents = (batch: EventDelivery[]) => owner.deliver(batch);
export const forgetDocumentEvents = () => owner.forget();
export const stopDocumentEvents = () => owner.stop();
