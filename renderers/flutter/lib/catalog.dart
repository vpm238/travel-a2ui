// The travel catalog, assembled from the A2UI SDK and fifteen travel views.
//
// The document arrives from `/api/catalog`: the same JSON the agent is taught
// from and the server validates against. `Catalog.fromJson` from `a2ui_core`
// reads it, keeping every schema as the document wrote it, and the binder
// resolves its `common_types.json` references itself.
//
// Then each entry gets an implementation:
//
// - a basic component (Text, Row, Button, Slider, ...) is `a2ui_flutter`'s own
//   widget, from `basicCatalog()`;
// - a basic function (formatString, pluralize, the checks, ...) is
//   `a2ui_core`'s own;
// - a travel component or function is ours, from `components.dart` and
//   `functions.dart`.
//
// Anything the document offers that none of those can draw or evaluate is an
// error here, at startup, rather than a hole in a surface later: the agent may
// use every component it is offered.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:a2ui_flutter/a2ui_flutter.dart';
import 'package:a2ui_flutter/basic_catalog.dart';

import 'components.dart';
import 'functions.dart';

/// The renderer catalog for a travel catalog document.
CatalogImplementation travelCatalog(Map<String, Object?> document) {
  final CatalogApi api = Catalog.fromJson(document);
  final CatalogImplementation basic = basicCatalog();

  final missing = <String>[];

  final components = <ComponentImplementation>[];
  for (final ComponentApi component in api.components.values) {
    final ComponentImplementation? sdk = basic.components[component.name];
    final TravelView? view = travelViews[component.name];
    if (sdk != null) {
      components.add(sdk);
    } else if (view != null) {
      components.add(travelComponent(component, view));
    } else {
      missing.add('component ${component.name}');
    }
  }

  final functions = <FunctionImplementation>[];
  for (final FunctionApi function in api.functions.values) {
    final FunctionImplementation? sdk = basic.functions[function.name];
    final build = travelFunctions[function.name];
    if (sdk != null) {
      functions.add(sdk);
    } else if (build != null) {
      functions.add(build(function));
    } else {
      missing.add('function ${function.name}');
    }
  }

  if (missing.isNotEmpty) {
    throw A2uiCatalogError(
      "Catalog '${api.id}' offers ${missing.join(', ')}, which this client "
      'cannot render.',
      catalogId: api.id,
    );
  }

  return CatalogImplementation(
    id: api.id,
    components: components,
    functions: functions,
    protocolVersion: api.protocolVersion,
    themeSchema: api.themeSchema,
    definitions: api.definitions,
  );
}
