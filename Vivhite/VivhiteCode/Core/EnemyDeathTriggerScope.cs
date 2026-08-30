using System.Runtime.ExceptionServices;

namespace Vivhite.Core;

/// <summary>
/// Defers Vivhite enemy-death listeners while a wrapped attack is resolving. Scopes follow the
/// asynchronous action flow, so nested wrapped attacks own independent FIFO queues and restore
/// their parent when complete.
/// </summary>
internal sealed class EnemyDeathTriggerScope : IDisposable
{
    private static readonly AsyncLocal<EnemyDeathTriggerScope?> CurrentScope = new();

    private readonly object _gate = new();
    private readonly Queue<Func<Task>> _pending = new();
    private readonly EnemyDeathTriggerScope? _parent;

    private bool _accepting = true;
    private bool _flushStarted;
    private bool _disposed;

    private EnemyDeathTriggerScope(EnemyDeathTriggerScope? parent)
    {
        _parent = parent;
    }

    public static EnemyDeathTriggerScope Enter()
    {
        var scope = new EnemyDeathTriggerScope(CurrentScope.Value);
        CurrentScope.Value = scope;
        return scope;
    }

    /// <summary>
    /// Adds one listener invocation to the innermost active attack scope. A closed scope rejects
    /// late work so the caller can execute it immediately instead of losing the death event.
    /// </summary>
    public static bool TryEnqueue(Func<Task> listener)
    {
        ArgumentNullException.ThrowIfNull(listener);
        return CurrentScope.Value?.TryEnqueueInternal(listener) == true;
    }

    /// <summary>
    /// Executes queued listeners sequentially in native delivery order. Listener failures do not
    /// prevent later listeners from observing their already-claimed death events.
    /// </summary>
    public async Task FlushAsync()
    {
        lock (_gate)
        {
            if (_flushStarted)
            {
                throw new InvalidOperationException("An enemy-death scope can only be flushed once.");
            }

            _flushStarted = true;
        }

        List<ExceptionDispatchInfo>? failures = null;
        while (true)
        {
            Func<Task>? listener;
            lock (_gate)
            {
                if (_pending.Count == 0)
                {
                    _accepting = false;
                    break;
                }

                listener = _pending.Dequeue();
            }

            try
            {
                await listener();
            }
            catch (Exception exception)
            {
                failures ??= [];
                failures.Add(ExceptionDispatchInfo.Capture(exception));
            }
        }

        if (failures is null)
        {
            return;
        }

        if (failures.Count == 1)
        {
            failures[0].Throw();
            throw new InvalidOperationException("Unreachable after rethrowing a deferred listener failure.");
        }

        throw new AggregateException(
            "Multiple deferred enemy-death listeners failed.",
            failures.Select(failure => failure.SourceException));
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        if (ReferenceEquals(CurrentScope.Value, this))
        {
            CurrentScope.Value = _parent;
        }
    }

    private bool TryEnqueueInternal(Func<Task> listener)
    {
        lock (_gate)
        {
            if (!_accepting)
            {
                return false;
            }

            _pending.Enqueue(listener);
            return true;
        }
    }
}
