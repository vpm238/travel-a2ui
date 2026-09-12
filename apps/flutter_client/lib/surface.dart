// Drawing one surface, through the core's binder.
//
// The binder is where the protocol actually happens: it walks a component's
// schema, follows every `{path}` into the data model, runs every
// `{call, args}` through the catalog's functions, and publishes the result as a
// signal. This widget subscribes to that signal and rebuilds when it changes.
//
// Which is why a data-model update repaints without any component being re-sent.
// The server draws the layout the moment a search begins and pushes only rows
// when they land; nothing here is told that a fill has happened, and nothing
// needs to be.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:flutter/material.dart';

import 'catalog.dart';
import 'components.dart';

/// One A2UI surface.
class A2uiSurface extends StatelessWidget {
  const A2uiSurface({super.key, required this.surface});

  final SurfaceModel<FlutterComponent> surface;

  @override
  Widget build(BuildContext context) {
    return _SurfaceRoot(surface: surface);
  }
}

/// Finds the root and redraws when the component set changes.
///
/// The core has no notion of a root: `updateComponents` is a flat list, and
/// which one is the top is left to the renderer. So it is resolved the same way
/// the compiler does — `root` by convention, and otherwise the one component
/// nothing else lists as a child, which is the same thing said structurally.
class _SurfaceRoot extends StatefulWidget {
  const _SurfaceRoot({required this.surface});

  final SurfaceModel<FlutterComponent> surface;

  @override
  State<_SurfaceRoot> createState() => _SurfaceRootState();
}

class _SurfaceRootState extends State<_SurfaceRoot> {
  void Function()? _created;
  void Function()? _deleted;

  @override
  void initState() {
    super.initState();
    void refresh(Object _) {
      if (mounted) setState(() {});
    }

    // Components arrive after the surface exists, and often in several
    // messages. Without this the first `updateComponents` would paint and the
    // rest would be invisible until something else forced a rebuild.
    widget.surface.componentsModel.onCreated.addListener(refresh);
    widget.surface.componentsModel.onDeleted.addListener(refresh);
    _created = () => widget.surface.componentsModel.onCreated.removeListener(refresh);
    _deleted = () => widget.surface.componentsModel.onDeleted.removeListener(refresh);
  }

  @override
  void dispose() {
    _created?.call();
    _deleted?.call();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final rootId = rootOf(widget.surface);
    if (rootId == null) {
      // A surface exists but has no components yet — the gap between
      // `createSurface` and `updateComponents`, which is a real state during
      // streaming and not an error.
      return const SizedBox.shrink();
    }
    return A2uiComponent(surface: widget.surface, componentId: rootId);
  }
}

/// The component everything else hangs off.
@visibleForTesting
String? rootOf(SurfaceModel<FlutterComponent> surface) {
  final all = surface.componentsModel.all.toList();
  if (all.isEmpty) return null;

  for (final component in all) {
    if (component.id == 'root') return component.id;
  }

  final claimed = <String>{};
  for (final component in all) {
    for (final value in component.properties.values) {
      if (value is List) {
        claimed.addAll(value.whereType<String>());
      } else if (value is Map && value['componentId'] is String) {
        claimed.add(value['componentId'] as String);
      }
    }
  }

  for (final component in all) {
    if (!claimed.contains(component.id)) return component.id;
  }
  return all.first.id;
}

/// One component, and its subtree.
class A2uiComponent extends StatefulWidget {
  const A2uiComponent({
    super.key,
    required this.surface,
    required this.componentId,
    this.basePath,
  });

  final SurfaceModel<FlutterComponent> surface;
  final String componentId;

  /// Where in the data model this component's relative bindings resolve from.
  ///
  /// A `_template` row binds `$airline`, not `$/flights/0/airline` — the same
  /// row definition is reused for every element, and the base path is what
  /// makes that work. Getting this wrong renders every row identically, which
  /// looks like a data bug and is not.
  final String? basePath;

  @override
  State<A2uiComponent> createState() => _A2uiComponentState();
}

class _A2uiComponentState extends State<A2uiComponent> {
  GenericBinder? _binder;
  ComponentContext? _context;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _rebind();
  }

  @override
  void didUpdateWidget(A2uiComponent old) {
    super.didUpdateWidget(old);
    if (old.componentId != widget.componentId || old.basePath != widget.basePath) {
      _rebind();
    }
  }

  void _rebind() {
    final model = widget.surface.componentsModel.get(widget.componentId);
    if (model == null) {
      _binder = null;
      _context = null;
      return;
    }
    final definition = widget.surface.catalog.components[model.type];
    if (definition == null) {
      _binder = null;
      _context = null;
      return;
    }
    _binder?.dispose();
    final context = ComponentContext(widget.surface, model, basePath: widget.basePath);
    _context = context;
    _binder = GenericBinder(context, definition.schema);
  }

  @override
  void dispose() {
    _binder?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final binder = _binder;
    final componentContext = _context;
    final model = widget.surface.componentsModel.get(widget.componentId);

    if (binder == null || componentContext == null || model == null) {
      return const SizedBox.shrink();
    }

    final definition = widget.surface.catalog.components[model.type];
    if (definition == null) return const SizedBox.shrink();

    return _Watch<Map<String, dynamic>>(
      signal: binder.resolvedProps,
      builder: (context, props) {
        final build = ComponentBuild(
          props: props ?? const {},
          context: componentContext,
          child: (id) => A2uiComponent(
            surface: widget.surface,
            componentId: id,
            basePath: widget.basePath,
          ),
          children: (property) => _childrenOf(props ?? const {}, property),
        );
        return definition.build(context, build);
      },
    );
  }

  /// The widgets for a child-list property.
  ///
  /// Two shapes, and the second is what makes a list of flights one component
  /// rather than four. A plain list of ids draws each once; a
  /// `{componentId, path}` template draws the *same* component once per element
  /// of the bound array, each with its own base path.
  List<Widget> _childrenOf(Map<String, dynamic> props, String property) {
    final value = props[property];
    // A single-child property (`Button`'s face) resolves to one node rather
    // than a list of them.
    if (value is ChildNode) {
      return [
        A2uiComponent(
          surface: widget.surface,
          componentId: value.id,
          basePath: value.basePath,
        ),
      ];
    }
    if (value is! List) return const [];

    return [
      for (final entry in value)
        // The binder hands back `ChildNode`s, not maps and not bare ids — for
        // both shapes. A plain `[head, list]` becomes two nodes whose base path
        // is the parent's; a `{componentId, path}` template becomes one node
        // per element of the bound array, each carrying the path its own
        // relative bindings resolve against.
        //
        // That distinction is the whole of how `_template` works, and reading
        // it wrong is silent: matching on `Map` instead of `ChildNode` finds
        // nothing, every subtree renders empty, and the surface is structurally
        // perfect and completely blank.
        if (entry is ChildNode)
          A2uiComponent(
            key: ValueKey('${entry.id}@${entry.basePath}'),
            surface: widget.surface,
            componentId: entry.id,
            basePath: entry.basePath,
          )
        else if (entry is String)
          A2uiComponent(
            surface: widget.surface,
            componentId: entry,
            basePath: widget.basePath,
          ),
    ];
  }
}

/// Rebuilds when a signal changes.
///
/// The core's reactivity is preact_signals rather than Flutter's own, so this
/// is the one adapter between them. Subscribing in `initState` and disposing in
/// `dispose` is the whole of it — a missed unsubscribe here would keep a
/// deleted surface alive and repainting.
class _Watch<T> extends StatefulWidget {
  const _Watch({super.key, required this.signal, required this.builder});

  final ReadonlySignal<T> signal;
  final Widget Function(BuildContext, T?) builder;

  @override
  State<_Watch<T>> createState() => _WatchState<T>();
}

class _WatchState<T> extends State<_Watch<T>> {
  late T _value;
  void Function()? _unsubscribe;

  @override
  void initState() {
    super.initState();
    _value = widget.signal.value;
    _listen();
  }

  void _listen() {
    _unsubscribe?.call();
    _unsubscribe = widget.signal.subscribe((next) {
      if (!mounted) return;
      setState(() => _value = next);
    });
  }

  @override
  void didUpdateWidget(_Watch<T> old) {
    super.didUpdateWidget(old);
    if (!identical(old.signal, widget.signal)) {
      _value = widget.signal.value;
      _listen();
    }
  }

  @override
  void dispose() {
    _unsubscribe?.call();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, _value);
}
