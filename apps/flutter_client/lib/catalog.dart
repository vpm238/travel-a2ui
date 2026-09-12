// The catalog, fetched from the server rather than compiled into the client.
//
// This is the part of the project's claim that is easiest to state and hardest
// to keep honest: a client should know how to *draw* components and nothing
// about what a trip is. So the schemas are not written here. They arrive from
// `/api/catalog` — the same JSON the agent is taught from and the compiler
// validates against — and the only thing this file supplies is a widget per
// component name.
//
// Adding a component to the catalog therefore does not break this client. It
// renders as a labelled placeholder until somebody writes its widget, which is
// the right failure: a surface that is nine tenths drawable should draw nine
// tenths, with the gap visible.
//
// ## The `$ref` problem, which is the whole of the work here
//
// The catalog says a bindable string is
// `{"$ref": "…common_types.json#/$defs/DynamicString"}`. The core's binder does
// *not* resolve `$ref`: it walks the schema structurally, looking for a
// `properties.path` to decide "this is a binding" and a `properties.event` to
// decide "this is an action". A reference it cannot see through looks like an
// ordinary object, so every binding on every component would resolve to
// nothing and every surface would render blank — with no error, because a
// schema with unresolvable references is still a valid schema.
//
// So each reference is mapped to the core's *own* definition of that type.
// Inlining our copy of `common_types.json` would work too, and would be wrong
// in a way that only shows up later: the binder is the thing reading these, so
// the binder's own idea of what a DynamicString is has to be what it gets.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:flutter/widgets.dart';
import 'package:json_schema_builder/json_schema_builder.dart';

import 'components.dart';
import 'functions.dart';

/// A component this client can draw: the protocol's API, plus a builder.
class FlutterComponent extends ComponentApi {
  FlutterComponent(this.name, this.schema, this.build);

  @override
  final String name;

  @override
  final Schema schema;

  /// Draws one component from its resolved properties.
  final ComponentBuilder build;
}

/// A number that may be a literal, a binding, or a call.
///
/// The core defines `dynamicString` and `dynamicBoolean` but not this one;
/// composed here the same way rather than approximated with `Schema.number()`,
/// because approximating it is exactly how a bound price stops being bound.
final _dynamicNumber = Schema.combined(
  description: r'REF:common_types.json#/$defs/DynamicNumber',
  anyOf: [Schema.number(), CommonSchemas.dataBinding, CommonSchemas.functionCall],
);

/// Every reference the travel catalog uses, and the core schema it means.
final Map<String, Schema> _knownRefs = {
  'DynamicString': CommonSchemas.dynamicString,
  'DynamicNumber': _dynamicNumber,
  'DynamicBoolean': CommonSchemas.dynamicBoolean,
  'ComponentId': CommonSchemas.componentId,
  'ChildList': CommonSchemas.childList,
  'Action': CommonSchemas.action,
  'Checkable': CommonSchemas.checkable,
  'DataBinding': CommonSchemas.dataBinding,
};

/// References that carry no binding behaviour and can be dropped.
///
/// `ComponentCommon` and `CatalogComponentCommon` contribute `id` and
/// `component`, which the processor reads directly off the message and the
/// binder has no opinion about. Keeping them would mean resolving a second
/// document to learn nothing.
const _ignoredRefs = {'ComponentCommon', 'CatalogComponentCommon'};

/// Builds the catalog from the server's own `catalog.json`.
Catalog<FlutterComponent> buildCatalog(Map<String, dynamic> catalogJson) {
  final definitions = (catalogJson['components'] as Map<String, dynamic>?) ?? {};

  final components = <FlutterComponent>[
    for (final entry in definitions.entries)
      FlutterComponent(
        entry.key,
        schemaFor(entry.value as Map<String, dynamic>),
        builderFor(entry.key),
      ),
  ];

  return Catalog<FlutterComponent>(
    // Read from the catalog rather than hardcoded, so this client can point at
    // a deployment that renamed its catalog without being rebuilt. It has to
    // match what the server puts on `createSurface`, or the processor refuses
    // the surface outright.
    id: (catalogJson[r'$id'] ?? catalogJson['catalogId']) as String,
    components: components,
    functions: catalogFunctions(),
  );
}

/// One component definition, with its references resolved.
@visibleForTesting
Schema schemaFor(Map<String, dynamic> definition) {
  final properties = <String, Schema>{};
  final required = <String>[];

  void absorb(Map<String, dynamic> node) {
    final props = node['properties'];
    if (props is Map) {
      props.forEach((key, value) {
        if (key == 'component' || key == 'id') return;
        if (value is Map<String, dynamic>) {
          properties[key as String] = _resolve(value);
        }
      });
    }
    final req = node['required'];
    if (req is List) {
      required.addAll(req.whereType<String>());
    }
    // `allOf` is how the catalog composes a component out of the common parts
    // and its own. Flattened here, because the binder reads properties and not
    // composition keywords.
    final allOf = node['allOf'];
    if (allOf is List) {
      for (final sub in allOf) {
        if (sub is Map<String, dynamic>) {
          final ref = _refName(sub);
          if (ref != null && _ignoredRefs.contains(ref)) continue;
          absorb(sub);
        }
      }
    }
  }

  absorb(definition);
  return Schema.object(
    properties: properties,
    required: required.where(properties.containsKey).toList(),
  );
}

String? _refName(Map<String, dynamic> node) {
  final ref = node[r'$ref'];
  if (ref is! String) return null;
  final hash = ref.lastIndexOf('/');
  return hash == -1 ? ref : ref.substring(hash + 1);
}

/// One property schema, with a reference swapped for what it refers to.
Schema _resolve(Map<String, dynamic> node) {
  final ref = _refName(node);
  if (ref != null) {
    final known = _knownRefs[ref];
    if (known != null) return known;
    // An unknown reference becomes a permissive schema rather than an error.
    // The alternative is refusing to draw a component over a property the
    // renderer may not even use.
    return Schema.combined(anyOf: [Schema.string(), CommonSchemas.dataBinding]);
  }

  // A nested composition — `anyOf` of a literal and a reference, say — is
  // resolved element-wise so the reference inside it is not missed.
  for (final keyword in ['anyOf', 'oneOf', 'allOf']) {
    final branches = node[keyword];
    if (branches is List) {
      final resolved = [
        for (final branch in branches)
          if (branch is Map<String, dynamic>) _resolve(branch),
      ];
      if (resolved.isNotEmpty) return Schema.combined(anyOf: resolved);
    }
  }

  if (node['type'] == 'array') {
    final items = node['items'];
    return Schema.list(
      items: items is Map<String, dynamic> ? _resolve(items) : null,
    );
  }

  if (node['type'] == 'object') {
    final props = node['properties'];
    return Schema.object(
      properties: props is Map
          ? {
              for (final entry in props.entries)
                if (entry.value is Map<String, dynamic>)
                  entry.key as String: _resolve(entry.value as Map<String, dynamic>),
            }
          : const {},
    );
  }

  return Schema.fromMap(node.cast<String, Object?>());
}
