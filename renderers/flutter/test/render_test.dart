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
import 'package:travel_a2ui_flutter/chat.dart';
import 'package:travel_a2ui_flutter/components.dart';
import 'package:travel_a2ui_flutter/surface.dart';

/// The wire version these fixtures declare.
///
/// Off the enum rather than written out, because the two SDKs spell 1.0
/// differently — `1.0` from Python, `v1.0` from Dart — and a literal here is a
/// third opinion. `readableVersion` is what reconciles the server's.
final String _wire = A2uiProtocolVersion.v1_0.jsonValue;

/// The repository root, from this file.
final _root = Directory.current.parent.parent;

Map<String, dynamic> _json(String relative) =>
    jsonDecode(File('${_root.path}/$relative').readAsStringSync()) as Map<String, dynamic>;

final Catalog<FlutterComponent, FunctionImplementation> _catalog =
    buildCatalog(_json('catalogs/a2ui-travel/catalog.json'));

// The version shim is the client's own `readableVersion`, imported rather than
// repeated. It used to be copied here "so the fixtures are the server's own
// bytes" — which was the right instinct and the wrong mechanism: the copy went
// on normalising `v0.9` long after the client had moved to 1.0, so the test
// agreed with itself about a conversion neither side still did.

MessageProcessor<FlutterComponent> _process(List<Map<String, dynamic>> messages) {
  final processor = MessageProcessor<FlutterComponent>(catalogs: [_catalog]);
  processor.processMessages([
    for (final message in messages) readableVersion(message),
  ]);
  return processor;
}

Future<void> _pump(WidgetTester tester, SurfaceModel<FlutterComponent> surface) async {
  // A window wide enough for a fare card.
  //
  // The default test surface is 800x600, and a `FlightOption` is a row of nine
  // facts — airline, number, both times, both airports, duration, stops,
  // price — which overflows it and fails the test on a layout assertion rather
  // than on anything it is checking. These cards are drawn in a chat column on
  // a real screen; 2000 is wide enough for the widest of them, and the height is for a list.
  tester.view.physicalSize = const Size(2000, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

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
      // `oneOf` on the v1.0 shapes, `anyOf` on the v0.9 ones. Either is a
      // union; what matters is that it is one, and that a binding is in it.
      final branches = (airline as Map)['oneOf'] ?? airline['anyOf'];
      expect(branches, isA<List>(), reason: 'a dynamic string is a union, not a bare type');
      // `@path` in 1.0, which is the rename this whole client had to follow.
      final hasPath = (branches as List).any(
        (branch) => branch is Map && (branch['properties'] as Map?)?.containsKey('@path') == true,
      );
      expect(hasPath, isTrue, reason: 'the binder finds a binding by looking for properties.@path');
    });

    test('a component this client does not draw is named, not dropped', () {
      // A surface that is nine tenths drawable should draw nine tenths.
      expect(_catalog.components.containsKey('Video'), isTrue);
      expect(drawnComponents.contains('Video'), isFalse);
    });
  });

  group('the skeleton, as the server sends it', () {
    late List<Map<String, dynamic>> opening;
    late List<Map<String, dynamic>> filled;
    late int blankRows;

    setUpAll(() {
      // Written by `tools/parity/skeleton.py` from the host's own
      // `opening_express` and `seed_rows`, so what is under test here is what
      // the server sends and not a hand-written approximation of it.
      final golden = _json('tools/parity/__golden__/skeleton.json');
      final flights = (golden['search_flights'] as Map).cast<String, dynamic>();
      opening = [
        for (final message in flights['opening'] as List)
          (message as Map).cast<String, dynamic>(),
      ];
      filled = [
        for (final message in flights['filled'] as List)
          (message as Map).cast<String, dynamic>(),
      ];
      // Off the golden, not a literal. This test asserted four for a while
      // after `SEEDED_ROWS` became three, and nothing caught it because the
      // golden it reads was never generated.
      blankRows = ((opening.last['updateDataModel'] as Map)['value'] as List).length;
    });

    testWidgets('it paints the layout before any data arrives', (tester) async {
      final processor = _process(opening);
      final surface = processor.model.getSurface('inline-1')!;
      await _pump(tester, surface);

      expect(find.text('Finding flights'), findsOneWidget);
    });

    testWidgets('the blank rows read as waiting, not as empty flights', (tester) async {
      final processor = _process(opening);
      final surface = processor.model.getSurface('inline-1')!;
      await _pump(tester, surface);

      // Each drawn from the one template component. If the pending state were
      // confused with empty, these would be flights with no airline and no
      // fare — which looks like an answer, and is worse than a spinner because
      // of it.
      expect(find.byType(InkWell), findsNWidgets(blankRows));
      expect(find.textContaining(r'$'), findsNothing);
    });

    testWidgets('the rows fill in when only the data model changes', (tester) async {
      final processor = _process(opening);
      final surface = processor.model.getSurface('inline-1')!;
      await _pump(tester, surface);

      // No components are re-sent. This is the whole of the UI-first claim: the
      // agent drew the shape once, and the search result is a data update.
      processor.processMessages([
        for (final message in filled) readableVersion(message),
      ]);
      await tester.pump();

      expect(find.text('Iberia'), findsOneWidget);
      expect(find.text(r'$412'), findsOneWidget);
      expect(find.text('18:40'), findsOneWidget);
    });
  });

  group('a template', () {
    testWidgets('repeats one component over an array, each row on its own data', (tester) async {
      final processor = _process([
        {
          'version': _wire,
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        },
        {
          'version': _wire,
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
          'version': _wire,
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {
                'id': 'row',
                'component': 'HotelCard',
                'name': {'@path': 'name'},
                'price': {'@path': 'price'},
                // Required by the catalog, and enforced from `a2ui_core` 0.4
                // where 0.1 let it pass. A stay nobody can choose is a
                // screenshot, which is the catalog's own argument for it.
                'action': {
                  'event': {
                    'name': 'select_hotel',
                    'context': {'id': {'@path': 'id'}},
                  },
                },
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

      await _pump(tester, processor.model.getSurface('s')!);

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
      final actions = <A2uiRendererAction>[];
      final processor = MessageProcessor<FlutterComponent>(
        catalogs: [_catalog],
        onAction: actions.add,
      );
      processor.processMessages([
        {
          'version': _wire,
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        },
        {
          'version': _wire,
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {
                'id': 'root',
                'component': 'TravelerCounter',
                'label': 'Travellers',
                'value': {'@path': '/trip/travelers'},
              },
            ],
          },
        },
      ]);

      final surface = processor.model.getSurface('s')!;
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
      final actions = <A2uiRendererAction>[];
      final processor = MessageProcessor<FlutterComponent>(
        catalogs: [_catalog],
        onAction: actions.add,
      );
      processor.processMessages([
        {
          'version': _wire,
          'createSurface': {'surfaceId': 's', 'catalogId': _catalog.id},
        },
        {
          'version': _wire,
          'updateComponents': {
            'surfaceId': 's',
            'components': [
              {'id': 'buttonLabel', 'component': 'Text', 'text': 'Search flights'},
              {
                'id': 'root',
                'component': 'Button',
                // A `child` component id, which the catalog requires and 0.4
                // enforces — `label` was never one of its properties.
                'child': 'buttonLabel',
                'action': {
                  'event': {
                    'name': 'search_flights',
                    'context': {'origin': {'@path': '/trip/origin'}},
                  },
                },
              },
            ],
          },
        },
      ]);

      final surface = processor.model.getSurface('s')!;
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

  group('a TripCalendar, from the parity golden', () {
    // The same bytes the TypeScript compiler and the reference compiler agree
    // on for `tools/parity/cases/21-trip-calendar.express`: two calendars, one
    // bound to the trip's dates with three marks, one a single literal day.
    late List<Map<String, dynamic>> messages;

    setUpAll(() {
      final golden = jsonDecode(
        File('${_root.path}/tools/parity/expected/21-trip-calendar.json').readAsStringSync(),
      ) as List;
      messages = [for (final message in golden) (message as Map).cast<String, dynamic>()];
    });

    testWidgets('waits for the dates, then draws the band on them', (tester) async {
      final processor = _process(messages);
      final surface = processor.model.getSurface('parity-surface')!;
      await _pump(tester, surface);

      // The bound calendar has no dates yet; the literal one is drawn already.
      expect(find.text('Dates to come'), findsOneWidget);
      expect(find.text('Day trip to Toledo'), findsOneWidget);
      expect(find.text('May 2027'), findsOneWidget);

      processor.processMessages([
        {
          'version': _wire,
          'updateDataModel': {
            'surfaceId': 'parity-surface',
            'path': '/trip',
            'value': {'startDate': '2027-04-12', 'endDate': '2027-04-18'},
          },
        },
      ]);
      await tester.pump();

      expect(find.text('Dates to come'), findsNothing);
      expect(find.text('April 2027'), findsOneWidget);
      // The key names each glyph once; the two flights share a line.
      expect(find.text('Fly out'), findsOneWidget);
      expect(find.text('Fly home'), findsOneWidget);
      expect(find.text('Prado'), findsOneWidget);
      // An emoji mark is drawn as itself, in the cell and in the key.
      expect(find.text('🎨'), findsNWidgets(2));
      // A named glyph becomes an icon: two marked days, one key entry each.
      expect(find.byIcon(Icons.flight), findsNWidgets(4));
    });

    testWidgets('an inverted range is one day, not nothing', (tester) async {
      final processor = _process(messages);
      processor.processMessages([
        {
          'version': _wire,
          'updateDataModel': {
            'surfaceId': 'parity-surface',
            'path': '/trip',
            'value': {'startDate': '2027-04-18', 'endDate': '2027-04-12'},
          },
        },
      ]);
      final surface = processor.model.getSurface('parity-surface')!;
      await _pump(tester, surface);
      expect(find.text('April 2027'), findsOneWidget);
      expect(find.text('Dates to come'), findsNothing);
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
