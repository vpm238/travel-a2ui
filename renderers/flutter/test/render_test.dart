// Rendering real A2UI, from the real catalog.
//
// The messages here are not hand-written: they are the bytes the server
// actually sends, taken from `tools/parity/__golden__/skeleton.json`, and the
// catalog is `catalogs/a2ui-travel/catalog.json`. A test built on a simplified
// stand-in would pass while the client failed on everything the server emits,
// which is precisely the failure mode a second renderer exists to detect.
//
// Three things are worth the trouble of testing here, and all three fail
// silently rather than loudly:
//
//   1. The bindings resolve at all. The catalog describes a bindable string as
//      a `$ref` the core's binder does not follow, so without the resolution in
//      `catalog.dart` every surface renders structurally perfect and entirely
//      blank.
//   2. Pending is distinguishable from empty. The skeleton seeds four empty
//      rows; they must draw as waiting, not as four flights with no airline.
//   3. A `_template` repeats one component over an array, with each row bound
//      to its own element.

import 'dart:convert';
import 'dart:io';

import 'package:a2ui_core/a2ui_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_a2ui_flutter/catalog.dart';
import 'package:travel_a2ui_flutter/components.dart';
import 'package:travel_a2ui_flutter/surface.dart';

/// The repository root, from this file.
final _root = Directory.current.parent.parent;

Map<String, dynamic> _json(String relative) =>
    jsonDecode(File('${_root.path}/$relative').readAsStringSync()) as Map<String, dynamic>;

final Catalog<FlutterComponent> _catalog =
    buildCatalog(_json('catalogs/a2ui-travel/catalog.json'));

/// The version shim the client applies, repeated here so the fixtures are the
/// server's own bytes rather than edited ones.
Map<String, dynamic> _readable(Map<String, dynamic> message) {
  final version = message['version'];
  if (version is String && version.startsWith('v0.9') && version != 'v0.9') {
    return {...message, 'version': 'v0.9'};
  }
  return message;
}

MessageProcessor<FlutterComponent> _process(List<Map<String, dynamic>> messages) {
  final processor = MessageProcessor<FlutterComponent>(catalogs: [_catalog]);
  processor.processMessages([
    for (final message in messages) A2uiMessage.fromJson(_readable(message)),
  ]);
  return processor;
}

Future<void> _pump(WidgetTester tester, SurfaceModel<FlutterComponent> surface) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: A2uiSurface(surface: surface)),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('the catalog', () {
    test('every component the server can send has a schema', () {
      final declared = _json('catalogs/a2ui-travel/catalog.json')['components'] as Map;
      expect(_catalog.components.length, declared.length);
    });

    test('the catalog id is what the server puts on createSurface', () {
      final catalogJson = _json('catalogs/a2ui-travel/catalog.json');
      expect(_catalog.id, catalogJson[r'$id']);
    });

    test('a bindable property is resolved into something the binder can follow', () {
      // The bug this guards: `{"$ref": "…#/$defs/DynamicString"}` is not
      // followed by the binder, so an unresolved schema means the property is
      // read as a plain object and the binding never fires. Every surface then
      // renders blank, with no error anywhere.
      final flight = _catalog.components['FlightOption']!;
      final airline = (flight.schema.value['properties'] as Map)['airline'];
      expect(airline, isNotNull);
      final branches = (airline as Map)['anyOf'];
      expect(branches, isA<List>(), reason: 'a dynamic string is a union, not a bare type');
      final hasPath = (branches as List).any(
        (branch) => branch is Map && (branch['properties'] as Map?)?.containsKey('path') == true,
      );
      expect(hasPath, isTrue, reason: 'the binder finds a binding by looking for properties.path');
    });

    test('a component this client does not draw is named, not dropped', () {
      // A surface that is nine tenths drawable should draw nine tenths.
      expect(_catalog.components.containsKey('Video'), isTrue);
      expect(drawnComponents.contains('Video'), isFalse);
    });
  });

  group('the skeleton, as the server sends it', () {
    late List<Map<String, dynamic>> opening;

    setUpAll(() {
      final golden = _json('tools/parity/__golden__/skeleton.json');
      opening = [
        for (final message in (golden['search_flights'] as Map)['opening'] as List)
          (message as Map).cast<String, dynamic>(),
      ];
    });

    testWidgets('it paints the layout before any data arrives', (tester) async {
      final processor = _process(opening);
      final surface = processor.groupModel.getSurface('inline-1')!;
      await _pump(tester, surface);

      expect(find.text('Finding flights'), findsOneWidget);
    });

    testWidgets('the four blank rows read as waiting, not as empty flights', (tester) async {
      final processor = _process(opening);
      final surface = processor.groupModel.getSurface('inline-1')!;
      await _pump(tester, surface);

      // Four rows, each drawn from the one template component. If the pending
      // state were confused with empty, these would be four flights with no
      // airline and no fare — which looks like an answer, and is worse than a
      // spinner because of it.
      expect(find.byType(InkWell), findsNWidgets(4));
      expect(find.textContaining(r'$'), findsNothing);
    });

    testWidgets('the rows fill in when only the data model changes', (tester) async {
      final processor = _process(opening);
      final surface = processor.groupModel.getSurface('inline-1')!;
      await _pump(tester, surface);

      // No components are re-sent. This is the whole of the UI-first claim: the
      // agent drew the shape once, and the search result is a data update.
      processor.processMessages([
        A2uiMessage.fromJson({
          'version': 'v0.9',
          'updateDataModel': {
            'surfaceId': 'inline-1',
            'path': '/flights',
            'value': [
              {
                'id': 'IB614',
                'airline': 'Iberia',
                'departTime': '08:39',
                'arriveTime': '12:51',
                'origin': 'JFK',
                'destination': 'MAD',
                'price': r'$257',
                'duration': '7h 12m',
                'stops': 'Nonstop',
                'flightNumber': 'IB614',
              },
            ],
          },
        }),
      ]);
      await tester.pump();

      expect(find.text('Iberia'), findsOneWidget);
      expect(find.text(r'$257'), findsOneWidget);
      expect(find.text('08:39'), findsOneWidget);
    });
  });

  group('a template', () {
    testWidgets('repeats one component over an array, each row on its own data', (tester) async {
      final processor = _process([
        {
          'version': 'v0.9.1',
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        },
        {
          'version': 'v0.9.1',
          'updateDataModel': {
            'surfaceId': 's',
            'path': '/hotels',
            'value': [
              {'name': 'Hotel One', 'price': r'$120'},
              {'name': 'Hotel Two', 'price': r'$140'},
              {'name': 'Hotel Three', 'price': r'$160'},
            ],
          },
        },
        {
          'version': 'v0.9.1',
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {
                'id': 'row',
                'component': 'HotelCard',
                'name': {'path': 'name'},
                'price': {'path': 'price'},
              },
              {
                'id': 'root',
                'component': 'List',
                'children': {'componentId': 'row', 'path': '/hotels'},
              },
            ],
          },
        },
      ]);

      await _pump(tester, processor.groupModel.getSurface('s')!);

      // One component definition, three rows, three different names. Rendering
      // the same name three times is the failure that looks like a data bug and
      // is a base-path bug.
      expect(find.text('Hotel One'), findsOneWidget);
      expect(find.text('Hotel Two'), findsOneWidget);
      expect(find.text('Hotel Three'), findsOneWidget);
    });
  });

  group('the interaction model', () {
    testWidgets('an editor writes to the data model and sends nothing', (tester) async {
      final actions = <A2uiClientAction>[];
      final processor = MessageProcessor<FlutterComponent>(
        catalogs: [_catalog],
        onAction: actions.add,
      );
      processor.processMessages([
        A2uiMessage.fromJson({
          'version': 'v0.9',
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        }),
        A2uiMessage.fromJson({
          'version': 'v0.9',
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {
                'id': 'root',
                'component': 'TravelerCounter',
                'label': 'Travellers',
                'value': {'path': '/trip/travelers'},
              },
            ],
          },
        }),
      ]);

      final surface = processor.groupModel.getSurface('s')!;
      surface.dataModel.set('/trip/travelers', 2);
      await _pump(tester, surface);

      await tester.tap(find.byIcon(Icons.add_circle_outline));
      await tester.pump();

      // Dragging a slider or pressing a counter is somebody still answering.
      // Only a button means they are done.
      expect(surface.dataModel.get('/trip/travelers'), 3);
      expect(actions, isEmpty);
    });

    testWidgets('a button sends the action the surface declared', (tester) async {
      final actions = <A2uiClientAction>[];
      final processor = MessageProcessor<FlutterComponent>(
        catalogs: [_catalog],
        onAction: actions.add,
      );
      processor.processMessages([
        A2uiMessage.fromJson({
          'version': 'v0.9',
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        }),
        A2uiMessage.fromJson({
          'version': 'v0.9',
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {
                'id': 'root',
                'component': 'Button',
                'label': 'Search flights',
                'action': {
                  'event': {
                    'name': 'search_flights',
                    'context': {'origin': {'path': '/trip/origin'}},
                  },
                },
              },
            ],
          },
        }),
      ]);

      final surface = processor.groupModel.getSurface('s')!;
      surface.dataModel.set('/trip/origin', 'JFK');
      await _pump(tester, surface);

      await tester.tap(find.text('Search flights'));
      await tester.pump();

      expect(actions, hasLength(1));
      expect(actions.single.name, 'search_flights');
      // The context arrives resolved: the client sends what the traveller set,
      // not a path for the server to look up.
      expect(actions.single.context['origin'], 'JFK');
    });
  });

  group('the catalog functions', () {
    test('every function the catalog declares is implemented', () {
      // Driven from the catalog rather than from the code, so a function
      // declared and not implemented fails here. That is the gap `formatString`
      // shipped through on the React side: it never implemented its own spec,
      // nothing threw, and the tests agreed because they were written from the
      // implementation.
      final declared = (_json('catalogs/a2ui-travel/catalog.json')['functions'] as Map).keys;
      for (final name in declared) {
        expect(
          _catalog.functions.containsKey(name),
          isTrue,
          reason: '$name is declared in the catalog and not implemented',
        );
      }
    });

    test('nights are counted the way a hotel counts them', () {
      final nights = _catalog.functions['calcNights']!;
      final context = DataContext(DataModel(), _catalog.invoke, '/');
      expect(
        nights.execute({'start': '2027-04-12', 'end': '2027-04-15'}, context),
        3,
      );
      // A half-filled form shows a zero rather than nonsense, and a picker
      // mid-drag never briefly reads "-4 nights".
      expect(nights.execute({'start': '2027-04-12'}, context), 0);
      expect(
        nights.execute({'start': '2027-04-15', 'end': '2027-04-12'}, context),
        0,
      );
    });

    test('a currency is whole units, because a fare is', () {
      final format = _catalog.functions['formatCurrency']!;
      final context = DataContext(DataModel(), _catalog.invoke, '/');
      expect(format.execute({'value': 1240, 'currency': 'USD'}, context), r'$1,240');
    });
  });
}
