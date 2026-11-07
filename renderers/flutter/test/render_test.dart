// Rendering real A2UI, from the real catalog, with the A2UI Flutter SDK.
//
// The messages here are not hand-written where it matters: the flight list is
// `test/fixtures/flights.json`, the bytes the server sends when the model draws
// `Flights()` and the lookup returns (`scripts/build_fixtures.py`); every
// catalog example is `test/fixtures/examples.json`, each one as the server
// sends it, macros expanded and data filled
// (`tool/build_example_fixtures.py`); and every component's example is
// `apps/web/src/generated/catalog-reference.json`, which the build compiles
// with the A2UI Python SDK and validates before writing. The catalog is
// `catalogs/a2ui-travel/catalog.json`, read by `Catalog.fromJson`.
//
// What is under test is the assembly, not the SDK: that every component the
// agent is offered draws, that the basic ones are `a2ui_flutter`'s own, and
// that the fifteen travel views read what the SDK resolved for them.

import 'dart:convert';
import 'dart:io';

import 'package:a2ui_core/a2ui_core.dart';
import 'package:a2ui_flutter/a2ui_flutter.dart';
import 'package:a2ui_flutter/basic_catalog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_a2ui_flutter/catalog.dart';
import 'package:travel_a2ui_flutter/chat.dart' show TravelSurface;
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

Future<void> _pump(WidgetTester tester, SurfaceModel<ComponentImplementation> surface,
    {bool markdown = false}) async {
  // Wide enough for a fare card, tall enough for a list.
  tester.view.physicalSize = const Size(1400, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: markdown ? TravelSurface(surface: surface) : A2uiSurface(surface: surface),
        ),
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

    test('draws the fifteen travel components itself', () {
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

  group('every catalog example, as the server sends it', () {
    final examples = (jsonDecode(File('${_root.path}/renderers/flutter/test/fixtures/examples.json').readAsStringSync())
            as List)
        .cast<Map<String, dynamic>>();

    // What each example must put on screen: the words a traveller reads.
    const shows = <String, List<String>>{
      '10-opening-form': ['Madrid in April — two travellers', 'Where from?', 'Travel dates', 'Travellers', 'Find flights'],
      '20-flight-options': ['Outbound · JFK → MAD · Sun 12 Apr', 'Prices are per traveler, round trip.'],
      '30-refine-search': ['Refine', 'Travel dates', 'Adults', 'Max fare', 'Stops', 'Apply'],
      '40-trip-panel': ['Your trip to Madrid', 'JFK → Madrid', '12 Apr – 19 Apr · 2 travelling', 'Iberia', 'IB6250'],
      '50-itinerary-day': ['Day 2 — Old Madrid', 'Prado Museum', 'Lunch at Sobrino', 'Retiro Park', 'Packing'],
      '60-home-dashboard': ['17 days to Madrid', 'Booked', 'Budget left', 'Next up', 'Budget used', 'April 2027'],
      '70-traveler-form': ['Who is travelling?', 'Full name (as on passport)', 'Email', 'Seat', 'Save traveller'],
    };

    test('covers every example', () {
      expect(examples.map((example) => example['example']).toSet(), shows.keys.toSet());
    });

    for (final example in examples) {
      final name = example['example'] as String;
      testWidgets('$name draws what it says', (tester) async {
        final run = _Run();
        expect(run.apply((example['messages'] as List).cast<Object?>()), isEmpty);
        await _pump(tester, run.surface(example['surfaceId'] as String), markdown: true);
        expect(tester.takeException(), isNull);
        expect(run.errors, isEmpty);
        for (final words in shows[name] ?? const <String>[]) {
          expect(find.textContaining(words, findRichText: true), findsWidgets, reason: '$name: "$words"');
        }
        // Headings are rendered as headings, not shown with their markers.
        expect(find.textContaining('### ', findRichText: true), findsNothing, reason: name);
      });
    }

    testWidgets('the fares example draws a card for every row it was sent', (tester) async {
      final example = examples.firstWhere((example) => example['example'] == '20-flight-options');
      final messages = (example['messages'] as List).cast<Map<String, dynamic>>();
      final rows = messages
          .map((message) => message['updateDataModel'] as Map?)
          .firstWhere((update) => update?['path'] == '/flights')!['value'] as List;
      final run = _Run();
      run.apply(messages);
      await _pump(tester, run.surface('inline-2'), markdown: true);
      for (final row in rows.cast<Map>()) {
        expect(find.text(row['flightNumber'] as String), findsOneWidget);
      }
    });
  });

  group('a flight list, as the server sends it', () {
    final fixture = _json('renderers/flutter/test/fixtures/flights.json');
    final opening = (fixture['opening'] as List).cast<Object?>();
    final filled = (fixture['filled'] as List).cast<Object?>();
    final rows = (((filled.first as Map)['updateDataModel'] as Map)['value'] as List).cast<Map>();

    testWidgets('paints the heading before any data arrives, and no rows', (tester) async {
      final run = _Run();
      expect(run.apply(opening), isEmpty);
      await _pump(tester, run.surface('inline-1'));

      expect(find.textContaining('Finding flights', findRichText: true), findsOneWidget);
      // A row with no airline and no fare reads as a flight called nothing.
      expect(find.text(rows.first['airline'] as String), findsNothing);
    });

    testWidgets('fills the rows in when only the data model changes', (tester) async {
      final run = _Run();
      run.apply(opening);
      await _pump(tester, run.surface('inline-1'));

      expect(run.apply(filled), isEmpty);
      await tester.pump();

      expect(find.text(rows.first['airline'] as String), findsWidgets);
      expect(find.text(rows.first['departTime'] as String), findsWidgets);
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

    testWidgets('an airport is searched for and picked, not read off a list', (tester) async {
      final run = _Run();
      run.apply([
        _surface(
          's',
          [
            {
              'id': 'root',
              'component': 'AirportPicker',
              'label': 'Where from?',
              'value': {'@path': '/trip/origin'},
              'kind': 'origin',
              'options': [
                {'value': 'JFK', 'label': 'New York', 'code': 'JFK', 'detail': 'North america'},
                {'value': 'CPH', 'label': 'Copenhagen', 'code': 'CPH', 'detail': 'Europe'},
                {'value': 'SFO', 'label': 'San Francisco', 'code': 'SFO', 'detail': 'North america'},
              ],
            },
          ],
          data: {'trip': <String, Object?>{}},
        ),
      ]);
      final surface = run.surface('s');
      await _pump(tester, surface);

      expect(find.byType(Radio<Object?>), findsNothing);
      await tester.tap(find.byIcon(Icons.flight_takeoff));
      await tester.pumpAndSettle();
      expect(find.text('San Francisco'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'cop');
      await tester.pumpAndSettle();
      expect(find.text('San Francisco'), findsNothing);
      await tester.tap(find.text('Copenhagen'));
      await tester.pumpAndSettle();

      expect(surface.dataModel.get('/trip/origin'), 'CPH');
      expect(find.text('Copenhagen'), findsOneWidget);
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

  group('the travel views read the catalog', () {
    // Every property a view reads must be one the catalog declares for that
    // component, or an item property of one of its arrays. A view reading a
    // name the catalog never mentions draws nothing for a field the agent
    // filled in.
    test('reads only properties its catalog entry declares', () {
      final source = File('lib/components.dart').readAsStringSync();
      final map = source.substring(source.indexOf('travelViews'));
      final views = {
        for (final match in RegExp(r"'(\w+)':\s*(_\w+),").allMatches(map)) match.group(1)!: match.group(2)!,
      };
      expect(views, isNotEmpty);
      const common = {'weight', 'accessibility', 'id', 'checks'};
      final problems = <String>[];
      for (final MapEntry(key: component, value: function) in views.entries) {
        final start = source.indexOf('Widget $function(BuildContext context, TravelProps build) {');
        expect(start, isNot(-1), reason: function);
        final rest = source.substring(start + 1);
        final end = RegExp(r'\n(Widget |class |final |const |typedef |String |DateTime|bool |///|// -)').firstMatch(rest);
        final body = end == null ? rest : rest.substring(0, end.start);

        final declared = <String>{};
        final items = <String>{};
        final schema = (_document['components'] as Map)[component] as Map;
        for (final part in (schema['allOf'] as List? ?? [schema])) {
          final properties = (part as Map)['properties'] as Map? ?? {};
          for (final MapEntry(:key, :value) in properties.entries) {
            declared.add('$key');
            final itemProperties = ((value as Map)['items'] as Map?)?['properties'] as Map?;
            if (itemProperties != null) items.addAll(itemProperties.keys.map((k) => '$k'));
          }
        }

        final top = {
          ...RegExp(r"build\.(?:string|number|flag|pending|absent|has|fire|write|children|value)\('(\w+)'")
              .allMatches(body)
              .map((m) => m.group(1)!),
          ...RegExp(r"build\['(\w+)'\]").allMatches(body).map((m) => m.group(1)!),
          ...RegExp(r"_\w+\(build, '(\w+)'").allMatches(body).map((m) => m.group(1)!),
        };
        final itemReads = RegExp(r"\b(\w+)\['(\w+)'\]")
            .allMatches(body)
            .where((m) => m.group(1) != 'build')
            .map((m) => m.group(2)!)
            .toSet();
        final undeclared = top.difference(declared).difference(common);
        final undeclaredItems = itemReads.difference(items).difference(declared);
        if (undeclared.isNotEmpty || undeclaredItems.isNotEmpty) {
          problems.add('$component reads $undeclared (items $undeclaredItems)');
        }
      }
      expect(problems, isEmpty);
    });

    // The other direction: a property the catalog offers the agent and the
    // view never reads is a field the agent fills in for nothing.
    test('reads every property its catalog entry declares', () {
      final source = File('lib/components.dart').readAsStringSync();
      final map = source.substring(source.indexOf('travelViews'));
      final views = {
        for (final match in RegExp(r"'(\w+)':\s*(_\w+),").allMatches(map)) match.group(1)!: match.group(2)!,
      };
      // Read by the SDK or by `_accessible`, for every component alike.
      const common = {'component', 'weight', 'accessibility', 'id', 'checks', 'metadata'};
      // Only a drawn map has a camera to point: these place it, and this
      // client lists a map's places instead of drawing one.
      const cannotBeDrawn = {
        'GoogleMap': {'zoom', 'heading', 'tilt'},
      };
      final problems = <String>[];
      for (final MapEntry(key: component, value: function) in views.entries) {
        final start = source.indexOf('Widget $function(BuildContext context, TravelProps build) {');
        final rest = source.substring(start + 1);
        final end = RegExp(r'\n(Widget |class |final |const |typedef |String |DateTime|bool |///|// -)').firstMatch(rest);
        final body = end == null ? rest : rest.substring(0, end.start);
        final read = {
          ...RegExp(r"build\.(?:string|number|flag|pending|absent|has|fire|write|children|value)\('(\w+)'")
              .allMatches(body)
              .map((m) => m.group(1)!),
          ...RegExp(r"build\['(\w+)'\]").allMatches(body).map((m) => m.group(1)!),
          ...RegExp(r"_\w+\(build, '(\w+)'").allMatches(body).map((m) => m.group(1)!),
          if (body.contains('build.hasAction') || RegExp(r'build\.fire\b(?!\()').hasMatch(body)) 'action',
          // Passed by name to a local helper, as FlightOption's `end('departTime', 'origin', …)`.
          ...RegExp(r"\b[a-z]\w*\('(\w+)', '(\w+)'").allMatches(body).expand((m) => [m.group(1)!, m.group(2)!]),
        };
        final declared = <String>{};
        final schema = (_document['components'] as Map)[component] as Map;
        for (final part in (schema['allOf'] as List? ?? [schema])) {
          declared.addAll((((part as Map)['properties'] as Map?) ?? {}).keys.map((key) => '$key'));
        }
        final unread = declared.difference(read).difference(common).difference(cannotBeDrawn[component] ?? const {});
        if (unread.isNotEmpty) problems.add('$component never reads $unread');
      }
      expect(problems, isEmpty);
    });

    testWidgets('a HotelCard shows its badge, and when it is the one chosen', (tester) async {
      final run = _Run();
      run.apply([
        _surface('hotel', [
          {
            'id': 'root',
            'component': 'HotelCard',
            'name': 'Hotel Urban',
            'price': r'$180',
            'badge': 'Walkable',
            'selected': true,
            'action': {
              'event': {'name': 'select_hotel'},
            },
          },
        ]),
      ]);
      await _pump(tester, run.surface('hotel'));
      expect(find.text('WALKABLE'), findsOneWidget);
      // No `imageUrl`: the generated placeholder, not an empty space.
      expect(find.byIcon(Icons.hotel_outlined), findsOneWidget);
      final card = tester.widget<AnimatedContainer>(find.byType(AnimatedContainer));
      expect(((card.decoration as BoxDecoration).border as Border).top.width, 2);
    });

    testWidgets('a FlightOption says which cabin it is priced in', (tester) async {
      final run = _Run();
      run.apply([
        _surface('fare', [
          {
            'id': 'root',
            'component': 'FlightOption',
            'airline': 'Iberia',
            'departTime': '18:40',
            'arriveTime': '08:15 +1',
            'origin': 'JFK',
            'destination': 'MAD',
            'price': r'$1,900',
            'flightNumber': 'IB6250',
            'cabin': 'business',
            'action': {
              'event': {'name': 'select_flight'},
            },
          },
        ]),
      ]);
      await _pump(tester, run.surface('fare'));
      expect(find.text(' · Business'), findsOneWidget);
    });

    testWidgets('an accessibility label is what a screen reader hears', (tester) async {
      final semantics = tester.ensureSemantics();
      final run = _Run();
      run.apply([
        _surface('fare', [
          {
            'id': 'root',
            'component': 'FlightOption',
            'airline': 'Iberia',
            'departTime': '18:40',
            'arriveTime': '08:15 +1',
            'origin': 'JFK',
            'destination': 'MAD',
            'price': r'$412',
            'action': {
              'event': {'name': 'select_flight'},
            },
            'accessibility': {'label': r'Iberia IB6250, nonstop, $412'},
          },
        ]),
      ]);
      await _pump(tester, run.surface('fare'));
      expect(find.bySemanticsLabel(r'Iberia IB6250, nonstop, $412'), findsWidgets);
      // The label replaces the card's own text: the parts are not read separately.
      expect(find.bySemanticsLabel('Iberia'), findsNothing);
      semantics.dispose();
    });

    testWidgets('the money, the tiles and the map are pressable when they have an action', (tester) async {
      final run = _Run();
      final refused = run.apply([
        _surface('money', [
          {'id': 'root', 'component': 'Column', 'children': ['sum', 'tile', 'map']},
          {
            'id': 'sum',
            'component': 'PriceSummary',
            'lines': [
              {'label': 'Flights', 'amount': r'$824'},
            ],
            'total': r'$824',
            'actionLabel': 'Hold for 24h',
            'action': {
              'event': {'name': 'hold'},
            },
          },
          {
            'id': 'tile',
            'component': 'StatTile',
            'label': 'Budget left',
            'value': r'$1,176',
            'action': {
              'event': {'name': 'open_budget'},
            },
          },
          {
            'id': 'map',
            'component': 'MapPreview',
            'markers': [
              {'label': 'Sol', 'kind': 'stay', 'day': '2'},
            ],
            'action': {
              'event': {'name': 'open_map'},
            },
          },
        ]),
      ]);
      expect(refused.map((e) => e.error.message), isEmpty);
      await _pump(tester, run.surface('money'));
      await tester.tap(find.text('Hold for 24h'));
      await tester.tap(find.text('Budget left'));
      await tester.tap(find.text('Day 2 · Sol'));
      await tester.pump();
      expect(run.actions.map((action) => action.name), ['hold', 'open_budget', 'open_map']);
    });

    testWidgets('an ActivityItem shows where, how long, and whether it is done', (tester) async {
      final run = _Run();
      run.apply([
        _surface('stop', [
          {
            'id': 'root',
            'component': 'ActivityItem',
            'title': 'Prado Museum',
            'time': '10:00',
            'category': 'sight',
            'location': 'Paseo del Prado 23',
            'duration': '2h',
            'done': true,
            'action': {
              'event': {'name': 'open_activity'},
            },
          },
        ]),
      ]);
      await _pump(tester, run.surface('stop'));
      expect(find.text('Paseo del Prado 23 · 2h'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      await tester.tap(find.text('Prado Museum'));
      await tester.pump();
      expect(run.actions.single.name, 'open_activity');
    });

    testWidgets('a TravelerCounter shows its caption', (tester) async {
      final run = _Run();
      run.apply([
        _surface('who', [
          {'id': 'root', 'component': 'TravelerCounter', 'label': 'Adults', 'caption': 'Age 12+', 'value': 2},
        ]),
      ]);
      await _pump(tester, run.surface('who'));
      expect(find.text('Age 12+'), findsOneWidget);
    });

    testWidgets('a GoogleMap lists its centre, its single route and how it is travelled', (tester) async {
      final run = _Run();
      final refused = run.apply([
        _surface('map', [
          {
            'id': 'root',
            'component': 'GoogleMap',
            'center': {'lat': 40.4161, 'lng': -3.6912},
            'zoom': 14,
            'origin': {'lat': 40.4169, 'lng': -3.7035},
            'destination': {'lat': 40.4153, 'lng': -3.6845},
            'travelMode': 'walking',
          },
        ]),
      ]);
      expect(refused.map((e) => e.error.message), isEmpty);
      await _pump(tester, run.surface('map'));
      expect(find.text('40.42, -3.70 → 40.42, -3.68 on foot'), findsOneWidget);
      expect(find.text('Around 40.42, -3.69'), findsOneWidget);
    });

    testWidgets('an ItineraryDay draws its activities, which are its children', (tester) async {
      final run = _Run();
      run.apply([
        _surface('day', [
          {'id': 'root', 'component': 'ItineraryDay', 'title': 'Day 1 · Madrid', 'children': ['a', 'b']},
          {'id': 'a', 'component': 'ActivityItem', 'title': 'Prado Museum', 'time': '10:00'},
          {'id': 'b', 'component': 'ActivityItem', 'title': 'Dinner at Sobrino', 'time': '21:00'},
        ]),
      ]);
      await _pump(tester, run.surface('day'));
      expect(find.text('Day 1 · Madrid'), findsOneWidget);
      expect(find.text('Prado Museum'), findsOneWidget);
      expect(find.text('Dinner at Sobrino'), findsOneWidget);
      expect(run.errors, isEmpty);
    });

    testWidgets('an ExpenseSplit draws its title, total and every participant', (tester) async {
      final run = _Run();
      run.apply([
        _surface('split', [
          {
            'id': 'root',
            'component': 'ExpenseSplit',
            'title': 'Dinner at Sobrino',
            'total': '€96',
            'participants': [
              {'name': 'Ana', 'share': '€48', 'status': 'paid'},
              {'name': 'Ben', 'share': '€48', 'status': 'owes'},
            ],
            'actionLabel': 'Settle up',
            'action': {
              'event': {'name': 'settle'},
            },
          },
        ]),
      ]);
      await _pump(tester, run.surface('split'));
      expect(find.text('Dinner at Sobrino'), findsOneWidget);
      expect(find.text('€96'), findsOneWidget);
      expect(find.text('Ana'), findsOneWidget);
      expect(find.text('Ben'), findsOneWidget);
      expect(find.text('€48'), findsNWidgets(2));
      expect(find.text('paid'), findsOneWidget);
      expect(find.text('owes'), findsOneWidget);
      await tester.tap(find.text('Settle up'));
      await tester.pump();
      expect(run.actions.single.name, 'settle');
    });

    testWidgets('a ProgressMeter fills to value over max', (tester) async {
      final run = _Run();
      run.apply([
        _surface('meter', [
          {'id': 'root', 'component': 'ProgressMeter', 'label': 'Budget', 'value': 500, 'max': 2000},
        ]),
      ]);
      await _pump(tester, run.surface('meter'));
      final bar = tester.widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator));
      expect(bar.value, closeTo(0.25, 1e-9));
    });
  });
}
