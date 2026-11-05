// Rendering real A2UI, from the real catalog, with the A2UI Flutter SDK.
//
// The messages here are not hand-written where it matters: the skeleton is
// `tools/parity/__golden__/skeleton.json`, the bytes the server sends for a
// flight search, and every component's example is
// `apps/web/src/generated/catalog-reference.json`, which the build compiles
// with the A2UI Python SDK and validates before writing. The catalog is
// `catalogs/a2ui-travel/catalog.json`, read by `Catalog.fromJson`.
//
// What is under test is the assembly, not the SDK: that every component the
// agent is offered draws, that the basic ones are `a2ui_flutter`'s own, and
// that the fourteen travel views read what the SDK resolved for them.

import 'dart:convert';
import 'dart:io';

import 'package:a2ui_core/a2ui_core.dart';
import 'package:a2ui_flutter/a2ui_flutter.dart';
import 'package:a2ui_flutter/basic_catalog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_a2ui_flutter/catalog.dart';
import 'package:travel_a2ui_flutter/components.dart';

final String _wire = A2uiProtocolVersion.v1_0.jsonValue;

/// The repository root, from this file.
final _root = Directory.current.parent.parent;

Map<String, dynamic> _json(String relative) =>
    jsonDecode(File('${_root.path}/$relative').readAsStringSync()) as Map<String, dynamic>;

final Map<String, dynamic> _document = _json('catalogs/a2ui-travel/catalog.json');
final CatalogImplementation _catalog = travelCatalog(_document);

/// A processor on the travel catalog, recording what it reports.
class _Run {
  _Run() {
    processor.model.onAction.subscribe(actions.add);
    processor.model.onSurfaceCreated.subscribe((surface) => surface.onError.subscribe(errors.add));
  }

  final processor = MessageProcessor<ComponentImplementation>(
    catalogs: [_catalog],
    defaultVersion: A2uiProtocolVersion.v1_0,
  );
  final actions = <A2uiRendererAction>[];
  final errors = <A2uiRendererError>[];

  List<ErrorMessage> apply(List<Object?> messages) => processor.processMessagesWithErrors(messages);

  SurfaceModel<ComponentImplementation> surface(String id) => processor.model.getSurface(id)!;
}

Future<void> _pump(WidgetTester tester, SurfaceModel<ComponentImplementation> surface) async {
  // Wide enough for a fare card, tall enough for a list.
  tester.view.physicalSize = const Size(1400, 3000);
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

Map<String, Object?> _surface(String id, List<Map<String, Object?>> components, {Object? data}) => {
      'version': _wire,
      'createSurface': {
        'surfaceId': id,
        'catalogId': _catalog.id,
        'components': components,
        'dataModel': ?data,
      },
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('the catalog', () {
    test('is the travel catalog, by its own id', () {
      expect(_catalog.id, _document['catalogId']);
    });

    test('can draw every component the agent is offered', () {
      final offered = (_document['components'] as Map).keys.toSet();
      expect(_catalog.components.keys.toSet(), offered);
    });

    test("draws the basic components with the SDK's own widgets", () {
      final basic = basicCatalog();
      for (final name in basic.components.keys) {
        if (!_catalog.components.containsKey(name)) continue;
        expect(identical(_catalog.components[name], basic.components[name]), isTrue, reason: name);
      }
    });

    test('draws the fourteen travel components itself', () {
      final basic = basicCatalog();
      final travel = (_document['components'] as Map).keys.where((name) => !basic.components.containsKey(name));
      expect(travelViews.keys.toSet(), travel.toSet());
    });

    test('evaluates every function the agent is offered', () {
      final offered = (_document['functions'] as Map).keys.toSet();
      expect(_catalog.functions.keys.toSet(), offered);
    });

    test('refuses a catalog offering a component nothing here can draw', () {
      final components = Map<String, Object?>.of(_document['components'] as Map<String, dynamic>)
        ..['Teleporter'] = {
          'type': 'object',
          'properties': {
            'component': {'const': 'Teleporter'},
          },
        };
      final defs = Map<String, Object?>.of(_document[r'$defs'] as Map<String, dynamic>);
      final union = Map<String, Object?>.of(defs['anyComponent'] as Map<String, dynamic>);
      union['oneOf'] = [
        ...union['oneOf'] as List,
        {r'$ref': '#/components/Teleporter'},
      ];
      defs['anyComponent'] = union;
      final broken = {..._document, 'components': components, r'$defs': defs};
      expect(() => travelCatalog(broken), throwsA(isA<A2uiCatalogError>()));
    });
  });

  group("every component's reference example", () {
    final reference = _json('apps/web/src/generated/catalog-reference.json');
    for (final entry in reference['components'] as List) {
      final component = entry as Map<String, dynamic>;
      final messages = component['messages'] as List?;
      if (messages == null || messages.isEmpty) continue;
      final name = component['name'] as String;

      testWidgets('$name draws, with nothing refused', (tester) async {
        final run = _Run();
        expect(run.apply(messages), isEmpty);
        final id = ((messages.first as Map)['createSurface'] as Map)['surfaceId'] as String;
        await _pump(tester, run.surface(id));
        expect(tester.takeException(), isNull);
        expect(run.errors, isEmpty);
      });
    }
  });

  group('the skeleton, as the server sends it', () {
    final golden = _json('tools/parity/__golden__/skeleton.json');
    final flights = (golden['search_flights'] as Map).cast<String, dynamic>();
    final opening = (flights['opening'] as List).cast<Object?>();
    final filled = (flights['filled'] as List).cast<Object?>();

    testWidgets('paints the heading before any data arrives, and no rows', (tester) async {
      final run = _Run();
      expect(run.apply(opening), isEmpty);
      await _pump(tester, run.surface('inline-1'));

      expect(find.textContaining('Finding flights', findRichText: true), findsOneWidget);
      // A row with no airline and no fare reads as a flight called nothing.
      expect(find.textContaining(r'$'), findsNothing);
    });

    testWidgets('fills the rows in when only the data model changes', (tester) async {
      final run = _Run();
      run.apply(opening);
      await _pump(tester, run.surface('inline-1'));

      expect(run.apply(filled), isEmpty);
      await tester.pump();

      expect(find.text('Iberia'), findsOneWidget);
      expect(find.text(r'$412'), findsOneWidget);
      expect(find.text('18:40'), findsOneWidget);
    });
  });

  group('a template', () {
    testWidgets('repeats one component over an array, each row on its own data', (tester) async {
      final run = _Run();
      run.apply([
        _surface(
          's',
          [
            {
              'id': 'root',
              'component': 'List',
              'children': {'componentId': 'row', 'path': '/hotels'},
            },
            {
              'id': 'row',
              'component': 'HotelCard',
              'name': {'@path': 'name'},
              'price': {'@path': 'price'},
              'action': {
                'event': {
                  'name': 'select_hotel',
                  'context': {
                    'name': {'@path': 'name'},
                  },
                },
              },
            },
          ],
          data: {
            'hotels': [
              {'name': 'Hotel One', 'price': r'$120'},
              {'name': 'Hotel Two', 'price': r'$140'},
              {'name': 'Hotel Three', 'price': r'$160'},
            ],
          },
        ),
      ]);
      await _pump(tester, run.surface('s'));

      // The same name three times would be a base-path bug.
      expect(find.text('Hotel One'), findsOneWidget);
      expect(find.text('Hotel Two'), findsOneWidget);
      expect(find.text('Hotel Three'), findsOneWidget);

      await tester.tap(find.text('Hotel Two'));
      await tester.pump();
      expect(run.actions.single.name, 'select_hotel');
      expect(run.actions.single.context['name'], 'Hotel Two');
    });
  });

  group('the interaction model', () {
    testWidgets('an editor writes to the data model and sends nothing', (tester) async {
      final run = _Run();
      run.apply([
        _surface(
          's',
          [
            {
              'id': 'root',
              'component': 'TravelerCounter',
              'label': 'Travellers',
              'value': {'@path': '/trip/travelers'},
            },
          ],
          data: {
            'trip': {'travelers': 2},
          },
        ),
      ]);
      final surface = run.surface('s');
      await _pump(tester, surface);

      await tester.tap(find.byIcon(Icons.add_circle_outline));
      await tester.pump();

      // Pressing a counter is somebody still answering; only a button means
      // they are done.
      expect(surface.dataModel.get('/trip/travelers'), 3);
      expect(run.actions, isEmpty);
    });

    testWidgets('a button sends its action, and the surface its values', (tester) async {
      final run = _Run();
      run.apply([
        {
          'version': _wire,
          'createSurface': {
            'surfaceId': 's',
            'catalogId': _catalog.id,
            'sendDataModel': true,
            'components': [
              {
                'id': 'root',
                'component': 'Column',
                'children': ['origin', 'go'],
              },
              {
                'id': 'origin',
                'component': 'TextField',
                'label': 'From',
                'value': {'@path': '/trip/origin'},
              },
              {'id': 'goLabel', 'component': 'Text', 'text': 'Search flights'},
              {
                'id': 'go',
                'component': 'Button',
                'child': 'goLabel',
                'action': {
                  'event': {'name': 'search_flights', 'context': {}},
                },
              },
            ],
            'dataModel': {
              'trip': {'origin': 'JFK', 'travelers': 2},
            },
          },
        },
      ]);
      final surface = run.surface('s');
      await _pump(tester, surface);

      await tester.enterText(find.byType(TextField), 'EWR');
      await tester.tap(find.text('Search flights'));
      await tester.pump();

      expect(run.actions.single.name, 'search_flights');
      expect(surface.sendDataModel, isTrue);
      // What `chat.dart` attaches to the press: every value on the surface.
      expect(surface.dataModel.get('/'), {
        'trip': {'origin': 'EWR', 'travelers': 2},
      });
    });

    testWidgets('the row the trip chose is marked by `equals`', (tester) async {
      final run = _Run();
      run.apply([
        _surface(
          's',
          [
            {
              'id': 'root',
              'component': 'List',
              'children': {'componentId': 'row', 'path': '/rows'},
            },
            {
              'id': 'row',
              'component': 'CheckBox',
              'label': {'@path': 'id'},
              'value': {
                '@call': 'equals',
                'args': {
                  'a': {'@path': 'id'},
                  'b': {'@path': '/trip/chosen'},
                },
              },
            },
          ],
          data: {
            'rows': [
              {'id': 'IB6250'},
              {'id': 'AF242'},
            ],
            'trip': {'chosen': 'AF242'},
          },
        ),
      ]);
      await _pump(tester, run.surface('s'));

      final boxes = tester.widgetList<Checkbox>(find.byType(Checkbox)).map((box) => box.value).toList();
      expect(boxes, [false, true]);
    });
  });

  group('a TripCalendar bound to the trip', () {
    List<Map<String, Object?>> calendar() => [
          _surface('s', [
            {
              'id': 'root',
              'component': 'TripCalendar',
              'start': {'@path': '/trip/startDate'},
              'end': {'@path': '/trip/endDate'},
              'title': 'Madrid',
              'marks': [
                {'date': '2027-04-12', 'icon': 'plane', 'label': 'Fly out'},
                {'date': '2027-04-14', 'icon': '🎨', 'label': 'Prado'},
                {'date': '2027-04-18', 'icon': 'plane', 'label': 'Fly home'},
              ],
            },
          ]),
        ];

    testWidgets('waits for the dates, then draws the band on them', (tester) async {
      final run = _Run();
      run.apply(calendar());
      await _pump(tester, run.surface('s'));
      expect(find.text('Dates to come'), findsOneWidget);

      run.apply([
        {
          'version': _wire,
          'updateDataModel': {
            'surfaceId': 's',
            'path': '/trip',
            'value': {'startDate': '2027-04-12', 'endDate': '2027-04-18'},
          },
        },
      ]);
      await tester.pump();

      expect(find.text('Dates to come'), findsNothing);
      expect(find.text('April 2027'), findsOneWidget);
      expect(find.text('Fly out'), findsOneWidget);
      expect(find.text('Fly home'), findsOneWidget);
      expect(find.text('Prado'), findsOneWidget);
      // An emoji mark is drawn as itself, in the cell and in the key.
      expect(find.text('🎨'), findsNWidgets(2));
      // A named glyph becomes an icon: two marked days, one key entry each.
      expect(find.byIcon(Icons.flight), findsNWidgets(4));
    });

    testWidgets('an inverted range is one day, not nothing', (tester) async {
      final run = _Run();
      run.apply(calendar());
      run.apply([
        {
          'version': _wire,
          'updateDataModel': {
            'surfaceId': 's',
            'path': '/trip',
            'value': {'startDate': '2027-04-18', 'endDate': '2027-04-12'},
          },
        },
      ]);
      await _pump(tester, run.surface('s'));
      expect(find.text('April 2027'), findsOneWidget);
      expect(find.text('Dates to come'), findsNothing);
    });
  });

  group('the travel functions', () {
    final context = DataContext(DataModel(), _catalog.invoke, '/');

    test('nights are counted the way a hotel counts them', () {
      final nights = _catalog.functions['calcNights']!;
      expect(nights.execute({'start': '2027-04-12', 'end': '2027-04-15'}, context), 3);
      expect(nights.execute({'start': '2027-04-12T00:00:00Z', 'end': '2027-04-19'}, context), 7);
      // Across a month and a daylight-saving change.
      expect(nights.execute({'start': '2027-03-27', 'end': '2027-04-02'}, context), 6);
      expect(nights.execute({'start': '2027-04-12'}, context), 0);
      expect(nights.execute({'start': '2027-04-15', 'end': '2027-04-12'}, context), 0);
    });

    test('equals compares as text and never matches nothing chosen', () {
      final equals = _catalog.functions['equals']!;
      expect(equals.execute({'a': 'IB6250', 'b': 'IB6250'}, context), true);
      expect(equals.execute({'a': 'IB6250', 'b': 'AF242'}, context), false);
      expect(equals.execute({'a': 7, 'b': '7'}, context), true);
      expect(equals.execute({'a': '', 'b': ''}, context), false);
      expect(equals.execute({'a': 'IB6250'}, context), false);
    });

    test("a currency is the SDK's own formatCurrency", () {
      final format = _catalog.functions['formatCurrency']!;
      expect(format.runtimeType, basicCatalog().functions['formatCurrency']!.runtimeType);
      expect('${format.execute({'value': 1240, 'currency': 'USD'}, context)}', contains('1,240'));
    });
  });
}
