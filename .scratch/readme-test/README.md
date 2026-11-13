# AccessKing

A cross-domain message bus for Unity: **event bus**, **command bus** and theme keyed **schedules**.

- Decoupled, allocation aware dispatch: handlers are located by notification type, not by direct references.
- Every handler receives the notification through `in`/`ref`, so a notification can both carry data and be mutated by a command.
- Weak subscriptions follow the lifetime of a `UnityEngine.Object` owner and are dropped automatically once it is destroyed.
- Command handlers may return results, synchronous or asynchronous, without boxing the result collection in the common path.

## Requirements

- Unity 2021.3 or later.
- [UniTask](https://github.com/Cysharp/UniTask) (`com.cysharp.unitask`) is **optional**. When the package is present the asynchronous command handlers and the operation helpers are `UniTask` based; when it is absent they fall back to `Task` and the package has no external dependency. Declare it yourself in your project manifest if you want the `UniTask` flavour:

  ```json
  { "dependencies": { "com.cysharp.unitask": "2.5.5" } }
  ```

## Install

### Unity

Append following content to `Packages/manifest.json`:

**From [GIT](https://github.com/peroperogames/AccessKing):**

```json
{
  "dependencies":
  {
    "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#0.3.0-base"
  }
}
```

**From [NPMJS](https://www.npmjs.com/package/com.prpr.accessking/):**

```json
{
  "scopedRegistries":
  [
    {
      "name": "npmjs",
      "url": "https://registry.npmjs.org",
      "scopes": ["com.prpr"]
    }
  ],
  "dependencies":
  {
    "com.prpr.accessking": "0.3.0"
  }
}
```

**From [OpenUPM](https://openupm.com/packages/com.prpr.accessking/):**

```json
{
  "scopedRegistries":
  [
    {
      "name": "package.openupm.com",
      "url": "https://package.openupm.com",
      "scopes": ["com.prpr"]
    }
  ],
  "dependencies":
  {
    "com.prpr.accessking": "0.3.0"
  }
}
```

Or install via CLI:

```sh
openupm add com.prpr.accessking
```

## Concepts

| Term | Meaning |
| --- | --- |
| **Bus** | A bus is a communication structure defined on an entity; a bus may have unique domain access message types to determine the semantics of bus messages. |
| **Notification** | The data that travels through a bus. Any type implementing `INotification`. |
| **Message** | Message is an abstraction of the data exchanged between buses; it includes notifications and the conventions for exchanging notifications between entities. The message category is cross domain message type. |
| **Handler** | The entity attached to a bus that reacts to the notifications it receives. |
| **Schedule** | A collection of bus instances, i.e. a service locator. It binds every bus to a theme so that business code does not need to see the bus implementation. |

Two cross domain message type kinds are provided by default:

- **Event** — reacts to a system change. An event must not decide a result.
- **Command** — causes a system state change. A command may produce a result.

## Access bus

An access bus is an abstraction of a message pipeline that allows a specific type of message to be passed across domains; it is described by the `IAccessBus` interface.

### Event bus

An event bus broadcasts a single notification type to all of its handlers.

```csharp
// A custom notification.
public struct MyNotification : INotification
{
    public int value;
}

public class MyEvents : EventBus<MyNotification> { }
```

#### Subscribe, unsubscribe and broadcast

A type implementing `IEventHandler<TNotification>` can be registered on the bus of the matching notification type:

```csharp
public class MyHandler : IEventHandler<MyNotification>, IDisposable
{
    private readonly IEventBus<MyNotification> m_EventBus;

    public MyHandler(IEventBus<MyNotification> eventBus)
    {
        // Subscribe.
        eventBus.Subscribe(this);
        m_EventBus = eventBus;
    }

    // Handle the notification.
    void IEventHandler<MyNotification>.Handle(in MyNotification notification)
    {
        Debug.Log("Event happened. value = " + notification.value);
    }

    public void Dispose()
    {
        // Unsubscribe.
        m_EventBus.Unsubscribe(this);
    }
}
```

```csharp
public class GameManager : IDisposable
{
    private readonly MyEvents m_Events;
    private readonly MyHandler m_Handler;

    public GameManager(MyEvents events)
    {
        m_Events = events;
        m_Handler = new MyHandler(events);
    }

    public void Broadcast(int value)
    {
        m_Events.Broadcast(new MyNotification { value = value });
    }

    public void Dispose()
    {
        m_Handler.Dispose();
    }
}
```

`Broadcast`, `Subscribe` and `Unsubscribe` are also available as `Action`/`Func` overloads; the bus then waits for the `ParameterNotification<T1...T16>` or `Empty` notification type.

#### Delegate support

```csharp
// A bus that accepts a delegate with one parameter.
public class MyEvents : EventBus<ParameterNotification<int>> { } // Or: ParameterEventBus<int>

public class Foo : IDisposable
{
    private readonly MyEvents m_Events;

    public Foo(MyEvents events)
    {
        m_Events = events;
        // The method group is converted to IEventHandler<ParameterNotification<int>>.
        m_Events.Subscribe(Handle);
    }

    private void Handle(int value) => Debug.Log("Event happened. value = " + value);

    public void Dispose() => m_Events.Unsubscribe(Handle);
}
```

A parameterless delegate needs a bus bound to `Empty`:

```csharp
public class MySignals : EventBus<Empty> { } // Or: ParameterEventBus

public class Bar : IDisposable
{
    private readonly MySignals m_Signals;

    public Bar(MySignals signals)
    {
        m_Signals = signals;
        m_Signals.Subscribe(Handle);
    }

    private void Handle() => Debug.Log("Event happened.");

    public void Dispose() => m_Signals.Unsubscribe(Handle);
}
```

#### Weak subscriptions

An event bus may hold a **weak** reference to its handler. The bus then does not keep the handler alive: once the handler is collected (or, for a `UnityEngine.Object`, destroyed), the subscription is dropped automatically. This is the usual case for a `MonoBehaviour` that must stop listening after `Destroy`.

```csharp
// Damage event.
public struct HurtInfo : INotification
{
    public int damage;
    public int targetId;
}

public class HurtEvents : EventBus<HurtInfo>
{
    private static readonly Lazy<HurtEvents> s_Instance = new(() => new HurtEvents());
    public static HurtEvents instance => s_Instance.Value;
}

// Monster implementation.
public class Monster : MonoBehaviour, IEventHandler<HurtInfo>
{
    private const int characterId = 0x00001;
    private int m_Hp = 100;

    public void Awake()
    {
        // Register itself through a weak reference.
        HurtEvents.instance.SubscribeWeakly(this);
    }

    void IEventHandler<HurtInfo>.Handle(in HurtInfo hurtInfo)
    {
        if (hurtInfo.targetId != characterId) return;

        m_Hp -= hurtInfo.damage;
        if (m_Hp <= 0) Debug.Log("Monster dead.");
    }
}
```

Delegates can be subscribed weakly as well. The subscription is owned by a `UnityEngine.Object`, whose destruction removes it:

```csharp
// Params: (int damage, int targetId)
public class HurtEvents : EventBus<ParameterNotification<int, int>>
{
    private static readonly Lazy<HurtEvents> s_Instance = new(() => new HurtEvents());
    public static HurtEvents instance => s_Instance.Value;
}

public class Monster : MonoBehaviour
{
    private const int characterId = 0x00001;
    private int m_Hp = 100;

    public void Awake()
    {
        // "this" is the owner, i.e. the entity that decides the subscription lifetime.
        HurtEvents.instance.SubscribeWeakly(this, Hurt);
    }

    private void Hurt(int damage, int targetId)
    {
        if (targetId != characterId) return;

        m_Hp -= damage;
        if (m_Hp <= 0) Debug.Log("Monster dead.");
    }
}
```

Two rules matter here:

1. The owner **must** be a `UnityEngine.Object`. Unity reports a destroyed object as `null`, so the bus can tell a dead owner from a live one without waiting for a GC that may never run; ownership therefore also works for plain C# targets:

   ```csharp
   public class Monster : MonoBehaviour
   {
       private readonly HurtBehaviour m_Hurt = new();

       public void Awake()
       {
           // Correct: the subscription dies with the Monster, even though the target is a plain class.
           // Note that such a subscription cannot be removed with Unsubscribe(m_Hurt.Handle): its identity is
           // (this, Handle), so it only ends together with this MonoBehaviour.
           HurtEvents.instance.SubscribeWeakly(this, m_Hurt.Handle);
       }
   }

   public class HurtBehaviour
   {
       public void Handle(int damage, int targetId) => Debug.Log(damage + " -> " + targetId);
   }
   ```

2. A weak subscription is identified by **(owner, method)**, not by the delegate instance: `Unsubscribe` locates it from a freshly created delegate, and two `MonoBehaviour`s that expose the same method stay independent.

   The identity uses the **owner**, not the delegate target, so the two are only interchangeable when they are the same object. Subscribing with `SubscribeWeakly(this, Handle)` (owner and target are the same `MonoBehaviour`) can be removed by `Unsubscribe(Handle)`; with a separate target, as in `SubscribeWeakly(this, m_Hurt.Handle)`, the subscription is bound to the owner's lifetime and `Unsubscribe(Handle)` does not find it — it ends when the owner is destroyed.

```csharp
HurtEvents.instance.Unsubscribe(Handle); // Works for the weak subscription as well.
```

### Command bus

A command bus changes system state. Handlers are usually long lived and created by a **handler factory**, which lets the same bus work for many handler sets.

```csharp
public struct MyNotification : INotification
{
    public int value;
}

public class MyHandler : ICommandHandler<MyNotification>
{
    public void Handle(ref MyNotification notification) => notification.value = 15;
}

public void Test()
{
    // Register the handler in a hard coded factory.
    var factory = new RegistryCommandHandlerFactory();
    var myHandler = new MyHandler();
    factory.RegisterHandler(myHandler);

    // Tell the bus where its handlers come from.
    var commandBus = new CommandBus<MyNotification>(factory);

    var myNotification = new MyNotification();
    commandBus.Execute(ref myNotification);

    Debug.Log(myNotification.value); // 15

    // Unregister when the handler is no longer needed.
    factory.UnregisterHandler(myHandler);
}
```

`CommandBus<TNotification>` is also a factory container keyed by factory type, so a single bus can dispatch through several factories:

```csharp
var bus = new CommandBus<Empty>();
bus.AddFactory(new RegistryCommandHandlerFactory());
bus.AddFactory(new MyFactory());
```

#### Synchronous results

A handler may expose a result by adding a second generic argument. The result type does not have to be unique: `GetResults<TResult>()` filters the produced results by type.

```csharp
// No result.
private class MyHandler1 : ICommandHandler<MyNotification>
{
    public void Handle(ref MyNotification notification) => notification.value = 15;
}

// int result.
private class MyHandler2 : ICommandHandler<MyNotification, int>
{
    public void Handle(ref MyNotification notification) => notification.value = 15;
    public int GetResult() => 5;
    object IResultAvailable.GetResult() => GetResult();
}

// string result.
private class MyHandler3 : ICommandHandler<MyNotification, string>
{
    public void Handle(ref MyNotification notification) { }
    public string GetResult() => "Got Result";
    object IResultAvailable.GetResult() => GetResult();
}
```

```csharp
public void Test()
{
    var factory = new RegistryCommandHandlerFactory();
    factory.RegisterHandler(new MyHandler1());
    factory.RegisterHandler(new MyHandler2());
    factory.RegisterHandler(new MyHandler3());

    var commandBus = new CommandBus<MyNotification>(factory);
    var myNotification = new MyNotification();

    // Execute and get the operation that owns the results.
    var operation = commandBus.Execute(ref myNotification);

    var intResults = operation.GetResults<int>();       // [5]
    var stringResults = operation.GetResults<string>(); // ["Got Result"]

    Debug.Log(intResults[0]);
    Debug.Log(stringResults[0]);
}
```

Reading the results releases the pooled collection by default. To read several result types from the same operation, or to reuse a caller owned list, pass `autoRelease: false`:

```csharp
var intResults = operation.GetResults<int>(autoRelease: false);
var stringResults = operation.GetResults<string>();

// Caller owned list, released by the caller.
var cache = new List<string>();
operation.GetResults(cache, autoRelease: false);
```

> **Warning**
> Reading results synchronously blocks the calling thread. If a handler queues asynchronous work that resumes on the Unity thread, waiting for it from the same thread deadlocks. Use `GetResultsAsync` (below) or keep the asynchronous work off the Unity thread.

#### Asynchronous results

`IAsyncCommandHandler<TNotification>` returns a `UniTask`, and `IAsyncCommandHandler<TNotification, TResult>` returns a `UniTask<TResult>`:

```csharp
// Asynchronous handler.
private class AsyncHandler : IAsyncCommandHandler<MyNotification, string>
{
    public void Handle(ref MyNotification notification) => Debug.Log("Handling");

    public async UniTask<string> GetResult()
    {
        await UniTask.Delay(3000);
        return "Handle finish - async";
    }

    object IResultAvailable.GetResult() => GetResult();
}

// Synchronous handler.
private class SyncHandler : ICommandHandler<MyNotification, string>
{
    public void Handle(ref MyNotification notification) => Debug.Log("Handling");

    public string GetResult() => "Handle finish - sync";

    object IResultAvailable.GetResult() => GetResult();
}
```

```csharp
public async UniTask Test()
{
    var factory = new RegistryCommandHandlerFactory();
    factory.RegisterHandler(new AsyncHandler());
    factory.RegisterHandler(new SyncHandler());

    var commandBus = new CommandBus<MyNotification>(factory);
    var myNotification = new MyNotification();
    var operation = commandBus.Execute(ref myNotification);

    var stringResults = await operation.GetResultsAsync<string>();

    Debug.Log(stringResults[0]); // Handle finish - async
    Debug.Log(stringResults[1]); // Handle finish - sync
}
```

When only completion matters, `WhenAllDone` and `WhenAnyDone` wait for all or for any asynchronous handler:

```csharp
// Wait for any asynchronous handler.
await commandBus.Execute(ref myNotification).WhenAnyDone();

// Wait for every asynchronous handler.
await commandBus.Execute(ref myNotification).WhenAllDone();
```

#### Func and Action handlers

A command bus bound to `ParameterNotification<T1...T16>` or `Empty` accepts delegates directly:

```csharp
public async UniTask Test()
{
    var factory = new RegistryCommandHandlerFactory();

    // Delegates without and with a result.
    factory.RegisterActionHandler<int>(TestNonReturn);
    factory.RegisterFuncHandler(TestReturn1);
    factory.RegisterFuncHandler<int, int>(TestReturn2);
    factory.RegisterFuncHandler<int, Task<int>>(TestReturnAsync);

    // Collect every int and Task<int> result.
    var results = await new CommandBus<ParameterNotification<int>>(factory)
        .Execute(5)
        .GetResultsAsync<int>();

    foreach (var result in results) Debug.Log(result);

    factory.UnregisterActionHandler<int>(TestNonReturn);
    factory.UnregisterFuncHandler(TestReturn1);
    factory.UnregisterFuncHandler<int, int>(TestReturn2);
    factory.UnregisterFuncHandler<int, Task<int>>(TestReturnAsync);
}

private void TestNonReturn(int a) { }
private int TestReturn1() => 1;
private int TestReturn2(int a) => a;

private async Task<int> TestReturnAsync(int a)
{
    await Task.Delay(1000);
    return a;
}
```

## Access schedules

`IAccessSchedule<TTheme>` binds buses to themes. A theme is any key type: `string`, `enum`, `int`, `uint`, `Type`, and so on. Themes hide the bus implementation from business code and turn the observer pattern into a publish/subscribe one.

### EventSchedule

```csharp
public enum GameEvent
{
    GameStart,
    GameOver
}

public class GameEvents : EventSchedule<GameEvent>
{
    private static readonly Lazy<GameEvents> s_Instance = new(() => new GameEvents());
    public static GameEvents global => s_Instance.Value;
}
```

```csharp
public void Start()
{
    if (!GameEvents.global.ContainsBus(GameEvent.GameOver))
    {
        // Bind the theme to a bus.
        GameEvents.global.AddBus(GameEvent.GameOver, new ParameterEventBus<int>());
    }

    var eventBus = GameEvents.global.GetBus<ParameterNotification<int>>(GameEvent.GameOver);
    eventBus.Subscribe(Test);
    eventBus.Broadcast(15);
    eventBus.Unsubscribe(Test);

    // Clear the handlers, then the theme bindings.
    eventBus.Clear();
    GameEvents.global.Clear();
}

private void Test(int value) => Debug.Log("Test value = " + value);
```

`Require` bundles the lookup and the creation, and throws when the theme is already bound to another notification type:

```csharp
public void Start()
{
    var eventBus = GameEvents.global.Require<int>(GameEvent.GameOver);

    eventBus.Subscribe(Test);
    eventBus.Broadcast(15);
    eventBus.Unsubscribe(Test);
}
```

### Type themed schedules

With `Type` as the theme the bus type itself becomes the key, so `Require` takes no theme argument and the notification type cannot mismatch:

```csharp
public class GameEvents : EventSchedule<Type>
{
    private static readonly Lazy<GameEvents> s_Instance = new(() => new GameEvents());
    public static GameEvents global => s_Instance.Value;

    public class GameOver : ParameterEventBus<int> { }
    public class GameStart : ParameterEventBus { }
}

public void Start()
{
    var eventBus = GameEvents.global.Require<GameEvents.GameOver>();

    eventBus.Subscribe(Test);
    eventBus.Broadcast(15);
    eventBus.Unsubscribe(Test);
}
```

### CommandSchedule

`CommandSchedule<TTheme>` mirrors `EventSchedule<TTheme>` for command buses:

```csharp
public class GameCommands : CommandSchedule<Type>
{
    private static readonly Lazy<GameCommands> s_Instance = new(() => new GameCommands());
    public static GameCommands global => s_Instance.Value;

    public class GameOver : ParameterCommandBus<int> { }
    public class GameStart : ParameterCommandBus { }
}

public void Start()
{
    var commandBus = GameCommands.global.Require<GameCommands.GameOver>();

    // Get or create the factory of this bus.
    var factory = commandBus.RequireFactory<RegistryCommandHandlerFactory>();
    factory.RegisterActionHandler<int>(Test);

    commandBus.Execute(15);

    factory.UnregisterActionHandler<int>(Test);
}

private void Test(int value) => Debug.Log("Test value = " + value);
```

## Known Issues

- **NativeAOT cannot create weak delegate subscriptions whose notification carries value type parameters.** `SubscribeWeakly(owner, action)` builds its typed invoker through reflection, and NativeAOT only compiles generic instantiations whose type arguments are all reference types. A subscription over a value type parameter, for example `ParameterEventBus<int>`, therefore throws `NotSupportedException: ... is missing native code or metadata` on the first subscription, while parameterless subscriptions (`Empty`) and reference type parameters work. The limitation is NativeAOT only: the JIT never hits it, and Unity IL2CPP was verified with `Managed Stripping Level = High` plus `stripEngineCode` enabled, where all three cases pass without any `[Preserve]` attribute. Under NativeAOT subscribe an `IEventHandler<TNotification>` instead of a delegate, because that path only holds a weak reference and creates no generics at runtime.
